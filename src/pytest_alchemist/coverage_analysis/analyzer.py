"""Coverage.py artifact normalization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import coverage
import libcst as cst
from coverage import CoverageData
from libcst.metadata import CodeRange, MetadataWrapper, PositionProvider

from pytest_alchemist.coverage_analysis.models import (
    CoverageArcFact,
    CoverageArtifactMetadata,
    CoverageCollectionResult,
    CoverageEntity,
    CoverageLineFact,
    CoverageQuality,
)
from pytest_alchemist.database.facade import DatabaseFacade

VALID_PHASES = {"setup", "run", "teardown"}


class CoverageAnalyzer:
    """Collects and normalizes Coverage.py data.

    The analyzer records factual coverage observations only. It does not choose,
    rank, or minimize tests.
    """

    def __init__(self, database: DatabaseFacade) -> None:
        self._database = database

    def collect(self, test_report_path: str | Path) -> CoverageCollectionResult:
        """Normalize coverage facts from a test report."""

        return self.collect_from_report(test_report_path)

    def collect_from_report(self, test_report_path: str | Path) -> CoverageCollectionResult:
        """Read a test report, normalize its native `.coverage`, and persist facts."""

        report_path = Path(test_report_path)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        run_uid = str(report["uid"])
        project_root = Path(report["project_root"]).resolve()
        coverage_data = report.get("coverage") or {}
        coverage_path_value = coverage_data.get("coverage_sqlite_path")
        if not coverage_path_value:
            return self._unreadable_result(run_uid, "test report has no .coverage path")

        coverage_path = Path(coverage_path_value)
        if not coverage_path.exists():
            return self._unreadable_result(run_uid, f".coverage file is missing: {coverage_path}")

        try:
            data = CoverageData(basename=str(coverage_path))
            data.read()
        except Exception as error:  # Coverage.py raises several data exceptions.
            return self._unreadable_result(run_uid, f"could not read .coverage: {error}")

        contexts = set(data.measured_contexts())
        parsed_contexts = {
            context: parsed
            for context in contexts
            if (parsed := parse_pytest_context(context)) is not None
        }
        has_contexts = bool(parsed_contexts)
        has_arcs = data.has_arcs()
        warnings: list[str] = []
        if "" in contexts:
            warnings.append("empty coverage context was ignored for per-test facts")
        if not has_contexts:
            warnings.append("no pytest-cov test contexts found")
        if not has_arcs:
            warnings.append("coverage artifact has no branch arcs")

        entities: list[CoverageEntity] = []
        line_facts: list[CoverageLineFact] = []
        arc_facts: list[CoverageArcFact] = []
        covered_files: set[str] = set()
        source_mismatch = False
        partial = False
        next_entity_id = 1

        for measured_file in sorted(data.measured_files()):
            source_path = _resolve_project_file(project_root, measured_file)
            if source_path is None:
                source_mismatch = True
                warnings.append(f"measured file is outside project root: {measured_file}")
                continue
            if source_path.suffix != ".py":
                continue

            try:
                relative_file = source_path.relative_to(project_root).as_posix()
            except ValueError:
                source_mismatch = True
                warnings.append(f"measured file is outside project root: {measured_file}")
                continue

            try:
                file_index = build_file_entity_index(
                    project_root,
                    source_path,
                    start_id=next_entity_id,
                )
                next_entity_id += len(file_index.entities)
            except Exception as error:
                partial = True
                warnings.append(f"could not parse {relative_file}: {error}")
                continue

            entities.extend(file_index.entities)

            for context, (nodeid, phase) in parsed_contexts.items():
                data.set_query_context(context)
                for raw_line in data.lines(measured_file) or []:
                    entity = file_index.entity_for_line(raw_line)
                    line_facts.append(
                        CoverageLineFact(
                            nodeid=nodeid,
                            phase=phase,
                            entity_id=entity.id or 0,
                            raw_line=raw_line,
                            entity_line_offset=_line_offset(entity, raw_line),
                        )
                    )
                    covered_files.add(relative_file)

                for from_line, to_line in data.arcs(measured_file) or []:
                    entity = file_index.entity_for_arc(from_line, to_line)
                    from_offset = _line_offset(entity, from_line)
                    to_offset = _line_offset(entity, to_line)
                    arc_facts.append(
                        CoverageArcFact(
                            nodeid=nodeid,
                            phase=phase,
                            entity_id=entity.id or 0,
                            from_line=from_line,
                            to_line=to_line,
                            from_offset=from_offset,
                            to_offset=to_offset,
                            arc_hash=_arc_hash(entity, from_offset, to_offset),
                        )
                    )
                    covered_files.add(relative_file)
        data.set_query_context(None)

        quality = _quality(has_contexts, has_arcs, source_mismatch, partial)
        metadata = CoverageArtifactMetadata(
            run_uid=run_uid,
            path=str(coverage_path),
            sha256=_sha256(coverage_path),
            coverage_py_version=coverage.__version__,
            has_contexts=has_contexts,
            has_arcs=has_arcs,
            quality=quality,
        )
        self._database.save_coverage_artifact_metadata(metadata)
        self._database.replace_coverage_facts(run_uid, entities, line_facts, arc_facts)

        return CoverageCollectionResult(
            run_uid=run_uid,
            quality=quality,
            warnings=warnings,
            entity_count=len(entities),
            line_fact_count=len(line_facts),
            arc_fact_count=len(arc_facts),
            covered_files=sorted(covered_files),
            records=[],
            tests=self._database.list_tests(),
        )

    def _unreadable_result(self, run_uid: str | None, warning: str) -> CoverageCollectionResult:
        return CoverageCollectionResult(
            run_uid=run_uid,
            quality="unreadable",
            warnings=[warning],
            entity_count=0,
            line_fact_count=0,
            arc_fact_count=0,
            covered_files=[],
            records=[],
            tests=self._database.list_tests(),
        )


def parse_pytest_context(context: str) -> tuple[str, str] | None:
    """Parse a pytest-cov context into `(nodeid, phase)`."""

    if not context or "::" not in context:
        return None

    nodeid, separator, phase = context.rpartition("|")
    if not separator:
        return None

    normalized_phase = phase if phase in VALID_PHASES else "unknown"
    return nodeid, normalized_phase


@dataclass(frozen=True)
class _FileEntityIndex:
    entities: list[CoverageEntity]

    def entity_for_line(self, line: int) -> CoverageEntity:
        candidates = [
            entity
            for entity in self.entities
            if entity.start_line is not None
            and entity.end_line is not None
            and entity.start_line <= line <= entity.end_line
        ]
        if not candidates:
            return self.entities[0]
        return max(
            candidates,
            key=lambda entity: (
                entity.start_line or 0,
                -(entity.end_line or 0),
                entity.qualified_name or "",
            ),
        )

    def entity_for_arc(self, from_line: int, to_line: int) -> CoverageEntity:
        if from_line > 0:
            return self.entity_for_line(from_line)
        if to_line > 0:
            return self.entity_for_line(to_line)
        return self.entities[0]


def build_file_entity_index(
    project_root: Path,
    source_path: Path,
    start_id: int = 1,
) -> _FileEntityIndex:
    """Build module/class/function/method entities for one Python source file."""

    source = source_path.read_text(encoding="utf-8")
    module = cst.parse_module(source)
    wrapper = MetadataWrapper(module)
    relative_file = source_path.relative_to(project_root).as_posix()
    module_name = _module_name_from_path(source_path.relative_to(project_root))
    line_count = max(1, len(source.splitlines()))
    module_entity = CoverageEntity(
        id=start_id,
        file_path=relative_file,
        module_name=module_name,
        qualified_name=module_name,
        kind="module",
        start_line=1,
        end_line=line_count,
        normalized_hash=_hash_text(source),
        current_revision=1,
        parent_id=None,
    )
    visitor = _EntityVisitor(
        relative_file=relative_file,
        module_name=module_name,
        wrapper=wrapper,
        first_entity=module_entity,
        next_id=start_id + 1,
    )
    wrapper.visit(visitor)
    return _FileEntityIndex(visitor.entities)


class _EntityVisitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(
        self,
        *,
        relative_file: str,
        module_name: str,
        wrapper: MetadataWrapper,
        first_entity: CoverageEntity,
        next_id: int,
    ) -> None:
        self.relative_file = relative_file
        self.module_name = module_name
        self.wrapper = wrapper
        self.entities = [first_entity]
        self._stack: list[tuple[int, str, str]] = [
            (first_entity.id or 1, "module", module_name)
        ]
        self._next_id = next_id

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._push_entity(node, node.name.value, "class")
        return True

    def leave_ClassDef(self, original_node: cst.ClassDef) -> None:
        self._stack.pop()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        parent_kind = self._stack[-1][1]
        kind = "method" if parent_kind == "class" else "function"
        self._push_entity(node, node.name.value, kind)
        return True

    def leave_FunctionDef(self, original_node: cst.FunctionDef) -> None:
        self._stack.pop()

    def _push_entity(
        self,
        node: cst.ClassDef | cst.FunctionDef,
        name: str,
        kind: str,
    ) -> None:
        parent_id, _parent_kind, parent_qualified_name = self._stack[-1]
        qualified_name = f"{parent_qualified_name}.{name}"
        position = self.get_metadata(PositionProvider, node)
        entity = CoverageEntity(
            id=self._next_id,
            file_path=self.relative_file,
            module_name=self.module_name,
            qualified_name=qualified_name,
            kind=kind,
            start_line=position.start.line,
            end_line=position.end.line,
            normalized_hash=_hash_node(self.wrapper, node, position),
            current_revision=1,
            parent_id=parent_id,
        )
        self.entities.append(entity)
        self._stack.append((self._next_id, kind, qualified_name))
        self._next_id += 1


def _hash_node(
    wrapper: MetadataWrapper,
    node: cst.ClassDef | cst.FunctionDef,
    position: CodeRange,
) -> CoverageQuality:
    try:
        return _hash_text(wrapper.module.code_for_node(node))
    except Exception:
        return _hash_text(f"{position.start.line}:{position.end.line}")


def _module_name_from_path(relative_path: Path) -> str:
    path = relative_path.with_suffix("")
    parts = list(path.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else relative_path.stem


def _resolve_project_file(project_root: Path, measured_file: str) -> Path | None:
    candidate = Path(measured_file)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(project_root)
    except (OSError, ValueError):
        return None
    if not resolved.exists():
        return None
    return resolved


def _line_offset(entity: CoverageEntity, line: int) -> int | None:
    if line <= 0 or entity.start_line is None:
        return None
    return line - entity.start_line


def _arc_hash(
    entity: CoverageEntity,
    from_offset: int | None,
    to_offset: int | None,
) -> str:
    return _hash_text(
        "|".join(
            [
                entity.file_path,
                entity.qualified_name or "",
                str(from_offset),
                str(to_offset),
            ]
        )
    )


def _quality(
    has_contexts: bool,
    has_arcs: bool,
    source_mismatch: bool,
    partial: bool,
) -> str:
    if not has_contexts:
        return "missing_contexts"
    if not has_arcs:
        return "missing_arcs"
    if source_mismatch:
        return "source_mismatch"
    if partial:
        return "partial"
    return "complete"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
