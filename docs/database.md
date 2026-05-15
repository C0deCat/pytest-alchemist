# Database

`database` отвечает за долговременное хранение истории запусков, последнего
известного состояния тестов, ссылок на артефакты и текущего нормализованного
индекса покрытия.

На первом этапе база должна быть простой SQLite-базой внутри директории
целевого проекта:

```text
.pytest-alchemist-artifacts/
  pytest-alchemist.sqlite
  test-runs/
    <run-uid>/
      test_report.json
      stdout.txt
      stderr.txt
      coverage.json
      coverage.xml
```

SQLite хранит индексируемые и нормализованные данные. Крупные исходные
артефакты остаются файлами на диске, а в базе хранятся пути, формат, хеш и
связь с запуском.

## Границы ответственности

`database` не должен запускать pytest, читать git diff, парсить coverage.py или
выполнять статический анализ. Для тестовых запусков он принимает ссылку на
`test_report.json`, читает нормализованные данные и сохраняет их в SQLite.

Ожидаемые публичные операции:

- сохранить запуск тестов из `test_report.json`;
- сохранить coverage-артефакт, связанный с запуском;
- сохранить последнее известное состояние отдельных тестов, если оно есть в
  `runned_tests`;
- вернуть известные тесты, их последние длительности и исходы;
- хранить текущий нормализованный индекс покрытия отдельно от истории запусков.

SQLite-детали не должны протекать в остальные модули. Снаружи это должен быть
facade или набор repository-объектов.

## Основные решения

### Идентификатор запуска

Запуск тестов должен иметь стабильный `uid`. Этот же `uid` используется как имя
папки в:

```text
.pytest-alchemist-artifacts/test-runs/<run-uid>
```

В таблицах лучше использовать `run_uid TEXT`, а не числовой автоинкремент,
потому что внешний артефакт и запись в базе должны ссылаться друг на друга без
дополнительного маппинга.

### Список выбранных тестов

Список node id хранится как JSON-строка в `test_runs`:

```text
selected_nodeids_json TEXT NOT NULL DEFAULT '[]'
```

Пустой список означает полный прогон. Это совпадает с текущим контрактом
`test_runner`: `tests=None` или пустой список не ограничивает pytest по node id.

Если позже понадобится часто искать запуски по конкретному тесту, можно добавить
таблицу `test_run_items`. Для первичной схемы достаточно JSON-поля, потому что
текущая продуктовая модель хранит только последнее известное состояние каждого
теста.

### Coverage flag

Поле `coverage_enabled` в `test_runs` должно отвечать только на вопрос: был ли
запуск выполнен с включенным сбором покрытия.

Само покрытие не нужно хранить в этой таблице. Coverage имеет несколько уровней
детализации и отдельные источники данных, поэтому на текущем этапе
`test_runs` должен хранить только признак включенного сбора.

`coverage_artifacts` остаётся историческим слоем, связанным с конкретным
запуском. Нормализованные сущности и факты покрытия являются отдельным текущим
индексом проекта, который используют алгоритмы выбора тестов.

## Предлагаемая схема

### `test_runs`

Хранит факт запуска pytest.

```sql
CREATE TABLE test_runs (
  uid TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  exit_code INTEGER,
  duration_ms INTEGER,
  passed_count INTEGER,
  failed_count INTEGER,
  coverage_enabled INTEGER NOT NULL,
  selected_nodeids_json TEXT NOT NULL DEFAULT '[]',
  stdout_path TEXT,
  stderr_path TEXT,
  project_root TEXT NOT NULL,
  pytest_args_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
```

`status` может быть `running`, `passed`, `failed`, `error` или `cancelled`.

`selected_nodeids_json = '[]'` означает полный прогон. Непустой список означает,
что pytest был ограничен конкретными node id.

### `tests`

Хранит известные pytest node id.

```sql
CREATE TABLE tests (
  nodeid TEXT PRIMARY KEY,
  file_path TEXT NOT NULL,
  normalized_hash TEXT,
  current_revision INTEGER NOT NULL DEFAULT 1,
  last_seen_run_uid TEXT,
  last_duration_ms INTEGER,
  last_outcome TEXT,
  last_error_message TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  FOREIGN KEY (last_seen_run_uid) REFERENCES test_runs(uid)
);
```

Эта таблица нужна `diff_picker` и `minimizer`, чтобы получать кандидатов и
примерную длительность тестов без чтения всех исторических запусков. Она
хранит последнее известное состояние каждого теста, а не снимок последнего
глобального запуска: частичный запуск обновляет только реально выполненные
тесты. Пока runner не передает текст ошибки по test case, `last_error_message`
остаётся `NULL`.

### `coverage_artifacts`

Хранит ссылки на исходные файлы coverage.py.

```sql
CREATE TABLE coverage_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_uid TEXT NOT NULL,
  format TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_uid) REFERENCES test_runs(uid)
);
```

`format` может быть `json`, `xml`, `sqlite` или другой формат, если позже будет
сохраняться нативный `.coverage`-файл.

Raw artifact полезен для отладки и повторной нормализации, но не должен быть
основным источником запросов для `diff_picker`.

## Как хранить coverage

Coverage хранится в двух слоях:

- `coverage_artifacts` — исторические raw-артефакты, связанные с запуском;
- нормализованные таблицы — текущий проектный индекс покрытия без привязки к
  конкретному запуску.

### Raw coverage artifact

Сохраняется как файл в директории запуска и регистрируется в
`coverage_artifacts`.

Плюсы:

- можно перепарсить данные после изменения нормализации;
- проще отлаживать расхождения;
- база не раздувается большими JSON/XML-документами.

Минусы:

- неудобно делать SQL-запросы;
- формат зависит от coverage.py.

Поэтому raw artifact должен быть архивным источником, а не основной моделью.

### Текущий нормализованный индекс

```sql
CREATE TABLE coverage_entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT NOT NULL,
  module_name TEXT,
  qualified_name TEXT,
  kind TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  normalized_hash TEXT,
  current_revision INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER,
  FOREIGN KEY (parent_id) REFERENCES coverage_entities(id)
);

CREATE TABLE coverage_line_facts (
  nodeid TEXT NOT NULL,
  phase TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  raw_line INTEGER NOT NULL,
  entity_line_offset INTEGER,
  observed_entity_revision INTEGER NOT NULL,
  observed_test_revision INTEGER NOT NULL,
  last_confirmed_run_uid TEXT NOT NULL,
  last_confirmed_at TEXT NOT NULL,
  PRIMARY KEY (nodeid, phase, entity_id, raw_line),
  FOREIGN KEY (last_confirmed_run_uid) REFERENCES test_runs(uid),
  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
);

CREATE TABLE coverage_arc_facts (
  nodeid TEXT NOT NULL,
  phase TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  from_line INTEGER NOT NULL,
  to_line INTEGER NOT NULL,
  from_offset INTEGER,
  to_offset INTEGER,
  arc_hash TEXT NOT NULL,
  observed_entity_revision INTEGER NOT NULL,
  observed_test_revision INTEGER NOT NULL,
  last_confirmed_run_uid TEXT NOT NULL,
  last_confirmed_at TEXT NOT NULL,
  PRIMARY KEY (nodeid, phase, entity_id, from_line, to_line),
  FOREIGN KEY (last_confirmed_run_uid) REFERENCES test_runs(uid),
  FOREIGN KEY (entity_id) REFERENCES coverage_entities(id)
);
```

Факт покрытия считается свежим, когда зафиксированные в нём ревизии сущности и
теста совпадают с их текущими ревизиями. Для тестов `normalized_hash` строится по
телу конкретного теста, а не по всему файлу. На текущем этапе полный сбор
coverage просто целиком заменяет этот индекс; частичное обновление и повышение
ревизий будут добавлены позже.

## Почему не хранить все coverage в `test_runs`

`test_runs.coverage` как boolean полезен, но не должен становиться контейнером
для данных покрытия.

Причины:

- у одного запуска может быть несколько coverage-артефактов;
- raw coverage и нормализованное coverage имеют разные форматы и жизненный цикл;
- нормализованный coverage имеет собственный жизненный цикл и должен жить
  отдельно от истории запусков.

## MVP-порядок реализации

Рекомендуемый порядок:

1. Создать SQLite-файл в `.pytest-alchemist-artifacts/pytest-alchemist.sqlite`.
2. Реализовать `test_runs`, `tests`, `coverage_artifacts`.
3. Сохранять обычные запуски тестов и пути к stdout/stderr/coverage/report.
4. Обновлять последнее известное состояние в `tests` из `runned_tests`.
5. Поддерживать текущий нормализованный индекс coverage как полную заменяемую
   снимком структуру до появления частичных обновлений.

Такой порядок сохраняет историю запусков и текущий индекс покрытия раздельно,
пока проект ещё не нуждается в частичном обновлении покрытия.

## Открытые вопросы

- Какой режим per-test coverage будет выбран: coverage.py contexts или
  отдельные запуски тестов?
- Нужно ли хранить `.coverage` SQLite-файл как raw artifact вместе с JSON/XML?
- Нужно ли версионировать конфигурацию coverage, чтобы понимать, с какими
  `source`, `omit` и `include` был собран конкретный запуск?
- Нужно ли сразу поддерживать несколько source roots?
- Как долго хранить старые `test-runs` и когда чистить связанные записи из
  базы?
- Как именно сопоставлять сущности после перемещений и переименований перед
  частичным обновлением покрытия?
