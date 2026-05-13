# Test Runner

`test_runner` отвечает за запуск pytest в целевом проекте и возвращает
структурированный результат запуска в `application`.

Модуль не должен принимать решений о выборе тестов, анализировать покрытие,
работать с базой данных или напрямую вызывать другие доменные модули.

## Структура модуля

На текущем этапе `test_runner` состоит из:

- типов, описанных в `models.py`;
- экспортируемой функции `run_tests`.

Обертка в виде класса не нужна. Функция должна быть основным публичным API
модуля.

## Назначение

`test_runner` должен уметь:

- запускать полный набор pytest-тестов целевого проекта;
- запускать отдельный набор конкретных тестов по pytest node id;
- запускать тесты из рабочей директории целевого проекта;
- передавать pytest аргументы, необходимые для конкретного сценария запуска;
- фиксировать код завершения, длительность, количество успешных и упавших
  тестов;
- сохранять или возвращать ссылки на артефакты запуска, если они были
  запрошены сценарием.

Примеры pytest node id:

```text
tests/test_api.py::test_create_user
tests/test_api.py::TestUsers::test_delete_user
```

## Основные сценарии

### Запуск всех тестов

Используется для проверки проекта целиком и для первичного сбора покрытия.

Ожидаемое поведение:

```text
application
  -> test_runner.run_tests(project_path=..., tests=None)
  -> TestRunResult
```

Если список тестов не передан, `test_runner` запускает pytest без ограничения
по node id.

### Запуск выбранных тестов

Используется после работы `diff_picker` и `minimizer`, когда приложение уже
выбрало минимальный набор тестов.

Ожидаемое поведение:

```text
application
  -> test_runner.run_tests(project_path=..., tests=[...])
  -> TestRunResult
```

`test_runner` преобразует список `TestCase` или node id в аргументы pytest и
запускает только эти тесты.

## Coverage

Динамическое покрытие проекта действительно можно получить только через запуск
тестов с нужной конфигурацией pytest/coverage.py, например через `pytest-cov`.

Граница ответственности должна быть такой:

- `test_runner` умеет запускать pytest с включенным сбором coverage и возвращает
  результат запуска вместе с путем к coverage-артефакту;
- `coverage_analysis` умеет читать coverage-артефакт, нормализовать его и
  превращать в доменные `CoverageRecord`;
- `application` оркестрирует сценарий: просит `test_runner` выполнить тесты с
  coverage, затем передает полученный артефакт в `coverage_analysis`;
- `test_runner` не должен напрямую зависеть от `coverage_analysis`.

Такой вариант сохраняет модульные границы: запуск тестов и анализ покрытия
остаются разными задачами, а порядок шагов контролирует `application`.

Рекомендуемый поток:

```text
pytest-alchemist collect-coverage
  -> cli
  -> application.collect_coverage(...)
  -> test_runner.run_tests(..., collect_coverage="json")
  -> coverage_analysis.analyze_artifact(...)
  -> database.save_coverage_collection(...)
```

Для сценариев, где покрытие не нужно, `application` вызывает `test_runner` без
coverage-настроек:

```text
pytest-alchemist run-minimal --last-commits N
  -> cli
  -> application.run_minimal(...)
  -> diff_picker.pick_candidates(...)
  -> minimizer.minimize(...)
  -> test_runner.run_tests(..., collect_coverage=None)
  -> database.save_test_run(...)
```

## Почему не связывать `test_runner` с `coverage_analysis`

Прямая зависимость `test_runner -> coverage_analysis` смешивает две разные
ответственности:

- `test_runner` знает, как запустить pytest;
- `coverage_analysis` знает, как интерпретировать покрытие.

Если связать их напрямую, модуль запуска тестов начнет принимать аналитические
решения и станет сложнее переиспользоваться для обычных прогонов без coverage.
Кроме того, `application` потеряет явный контроль над use case: будет менее
очевидно, когда покрытие собирается, где оно парсится и где сохраняется.

## Контракт функции

Публичный API модуля:

```text
run_tests(
  project_path: str,
  tests: list | None = None,
  collect_coverage: "json" | "xml" | None = None,
) -> TestRunResult
```

Параметры:

- `project_path` - путь к целевому проекту, из которого нужно запускать pytest;
- `tests` - список конкретных тестов; если не передан, запускается весь набор
  тестов проекта;
- `collect_coverage` - формат coverage-отчета; если не передан, coverage не
  собирается.

Поддерживаемые значения `collect_coverage`:

- `json` - собрать coverage JSON;
- `xml` - собрать coverage XML;
- `None` - не собирать coverage.

## Контракт результата

```text
TestRunResult
  selected_tests -> list
  passed -> int
  failed -> int
  duration_seconds -> float
  exit_code -> int
  stdout_path? -> str
  stderr_path? -> str
  coverage? -> CoverageRunArtifact

CoverageRunArtifact
  coverage_xml_path? -> str
  coverage_json_path? -> str
```

`coverage` заполняется только если `run_tests` был вызван с
`collect_coverage`. Если coverage не собирался, `coverage` должен быть пустым.

## Pytest coverage command

Базовый запуск для сбора покрытия может выглядеть так:

```text
pytest --cov=. --cov-report=json:.pytest-alchemist-artifacts/test-runs/<run-id>/coverage.json --cov-report=term
```

Для выбранных тестов:

```text
pytest tests/test_api.py::test_create_user --cov=. --cov-report=json:.pytest-alchemist-artifacts/test-runs/<run-id>/coverage.json
```

Конкретные аргументы должны быть конфигурируемыми, потому что целевые проекты
могут использовать разные source roots, omit/include правила и настройки
pytest.

## Конфигурация

В будущем `test_runner` должен получать настройки из конфигурации приложения:

```toml
[tool.pytest-alchemist]
test_command = "pytest"
test_paths = ["tests"]
coverage_source = ["src"]
coverage_report_dir = ".pytest-alchemist-artifacts"
extra_pytest_args = []
```

Эти настройки должны интерпретироваться на уровне `application` или
конфигурационного слоя, а в `test_runner` передаваться уже как явные параметры
запуска.

## Dependency rule

Итоговое правило зависимостей:

```text
application -> test_runner
application -> coverage_analysis
test_runner -> no domain dependencies
coverage_analysis -> no dependency on test_runner runtime
```

`coverage_analysis` может использовать модели, описывающие coverage-артефакты,
если они вынесены в общий слой моделей или в сам `coverage_analysis`. Но
`test_runner` не должен вызывать `coverage_analysis` напрямую.
