# Test Runner

`test_runner` отвечает за запуск pytest в целевом проекте и сохранение
структурированного отчета запуска.

Модуль не должен принимать решений о выборе тестов, анализировать покрытие,
работать с базой данных или напрямую вызывать другие доменные модули.

## Структура модуля

Публичный API модуля - класс `TestRunner`.

```python
TestRunner().run_tests(
    project_path: str,
    tests: list[TestCase | str] | None = None,
    collect_coverage: "json" | "xml" | None = None,
    collects_tests: bool = True,
) -> str
```

Метод возвращает путь к:

```text
.pytest-alchemist-artifacts/test-runs/<run-uid>/test_report.json
```

## Назначение

`test_runner` умеет:

- запускать полный набор pytest-тестов целевого проекта;
- запускать конкретные pytest node id;
- запускать тесты из рабочей директории целевого проекта;
- сохранять stdout, stderr, coverage-артефакты и JSON-отчет;
- собирать per-test результаты через pytest hook, если `collects_tests=True`;
- возвращать ссылку на `test_report.json`.

Примеры pytest node id:

```text
tests/test_api.py::test_create_user
tests/test_api.py::TestUsers::test_delete_user
```

## Основные сценарии

### Запуск всех тестов

```text
application
  -> TestRunner().run_tests(project_path=..., tests=None)
  -> path/to/test_report.json
```

Если список тестов не передан, `test_runner` запускает pytest без ограничения
по node id. В отчете `selection.selected_tests` будет пустым списком.

### Запуск выбранных тестов

```text
application
  -> TestRunner().run_tests(project_path=..., tests=[...])
  -> path/to/test_report.json
```

`test_runner` преобразует список `TestCase` или node id в аргументы pytest и
запускает только эти тесты. В отчете `selection.selected_tests` всегда хранится
список node id строк.

## Per-test результаты

По умолчанию `collects_tests=True`. В этом режиме `TestRunner` подключает к
pytest plugin module `pytest_alchemist.test_runner.logger`, который пишет сырые
`pytest_runtest_logreport` данные в директорию запуска. После завершения
subprocess runner нормализует их в `runned_tests`.

Нормализация outcome:

- любой failed `setup`, `call` или `teardown` означает `failed`;
- иначе любой skipped phase означает `skipped`;
- иначе passed `call` означает `passed`.

Длительность отдельного теста считается как сумма `setup + call + teardown` и
сохраняется в миллисекундах.

Если `collects_tests=False` или pytest завершился до выполнения тестов,
`runned_tests` будет пустым объектом. Агрегированный `summary` в этом случае
строится fallback-парсингом stdout/stderr.

## Coverage

`test_runner` умеет запускать pytest с включенным сбором coverage и сохраняет
путь к raw artifact в `test_report.json`.

Поддерживаемые значения `collect_coverage`:

- `json` - собрать coverage JSON;
- `xml` - собрать coverage XML;
- `None` - не собирать coverage.

`coverage` в отчете равен `null`, если coverage не собирался.

## Формат `test_report.json`

```json
{
  "schema_version": 1,
  "uid": "<run_uid>",
  "project_root": "<absolute project path>",
  "started_at": "<UTC ISO timestamp>",
  "finished_at": "<UTC ISO timestamp>",
  "duration_seconds": 1.234,
  "exit_code": 0,
  "status": "passed",
  "pytest": {
    "args": ["python", "-m", "pytest"],
    "stdout_path": "<absolute stdout.txt path>",
    "stderr_path": "<absolute stderr.txt path>"
  },
  "selection": {
    "selected_tests": ["tests/test_sample.py::test_one"]
  },
  "summary": {
    "passed": 1,
    "failed": 0,
    "skipped": 0,
    "total": 1
  },
  "runned_tests": {
    "tests/test_sample.py::test_one": {
      "nodeid": "tests/test_sample.py::test_one",
      "outcome": "passed",
      "duration_ms": 12
    }
  },
  "coverage": {
    "format": "json",
    "coverage_json_path": "<absolute coverage.json path>",
    "coverage_xml_path": null
  },
  "artifacts": {
    "run_dir": "<absolute run dir>",
    "test_report_path": "<absolute test_report.json path>"
  }
}
```

`runned_tests` всегда объект, где ключ - pytest node id.

## Dependency rule

```text
application -> test_runner
application -> database
test_runner -> no domain dependencies
database -> reads test_report.json
```

`test_runner` не должен вызывать `database` или `coverage_analysis` напрямую.
