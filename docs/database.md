# Database

`database` отвечает за долговременное хранение истории запусков, результатов
тестов и ссылок на артефакты, которые создают другие модули.

На первом этапе база должна быть простой SQLite-базой внутри директории
целевого проекта:

```text
.pytest-alchemist-artifacts/
  pytest-alchemist.sqlite
  test-runs/
    <run-uid>/
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
выполнять статический анализ. Он только принимает уже подготовленные данные от
`application` и профильных модулей.

Ожидаемые публичные операции:

- сохранить запуск тестов;
- сохранить coverage-артефакт, связанный с запуском;
- вернуть известные тесты и их последние длительности.

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

Для MVP список node id можно хранить как JSON-строку в `test_runs`:

```text
selected_nodeids_json TEXT NOT NULL DEFAULT '[]'
```

Пустой список означает полный прогон. Это совпадает с текущим контрактом
`test_runner`: `tests=None` или пустой список не ограничивает pytest по node id.

Если позже понадобится часто искать запуски по конкретному тесту, можно добавить
таблицу `test_run_items`. Для первичной схемы достаточно JSON-поля и отдельной
таблицы результатов тестов, если pytest начнет возвращать подробные результаты
по test case.

### Coverage flag

Поле `coverage_enabled` в `test_runs` должно отвечать только на вопрос: был ли
запуск выполнен с включенным сбором покрытия.

Само покрытие не нужно хранить в этой таблице. Coverage имеет несколько уровней
детализации и отдельные источники данных, поэтому на текущем этапе
`test_runs` должен хранить только признак включенного сбора.

До реализации модуля coverage база должна фиксировать только raw artifact через
`coverage_artifacts`. Нормализованная схема покрытия будет спроектирована
отдельно, когда станет понятен контракт `coverage_analysis`.

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
  last_seen_run_uid TEXT,
  last_duration_ms INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  FOREIGN KEY (last_seen_run_uid) REFERENCES test_runs(uid)
);
```

Эта таблица нужна `diff_picker` и `minimizer`, чтобы получать кандидатов и
примерную длительность тестов без чтения всех исторических запусков.

### `test_results`

Хранит результат отдельного теста внутри запуска, когда эта информация доступна.

```sql
CREATE TABLE test_results (
  run_uid TEXT NOT NULL,
  nodeid TEXT NOT NULL,
  outcome TEXT NOT NULL,
  duration_ms INTEGER,
  error_message TEXT,
  PRIMARY KEY (run_uid, nodeid),
  FOREIGN KEY (run_uid) REFERENCES test_runs(uid),
  FOREIGN KEY (nodeid) REFERENCES tests(nodeid)
);
```

Для MVP эта таблица может появиться позже, если `test_runner` сначала возвращает
только агрегированные `passed` и `failed`.

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

До реализации `coverage_analysis` database-модуль не должен фиксировать
нормализованную схему покрытия. Сейчас достаточно сохранить связь запуска с
исходным coverage-артефактом.

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

## Почему не хранить все coverage в `test_runs`

`test_runs.coverage` как boolean полезен, но не должен становиться контейнером
для данных покрытия.

Причины:

- у одного запуска может быть несколько coverage-артефактов;
- raw coverage и нормализованное coverage имеют разные форматы и жизненный цикл;
- будущая нормализованная схема coverage должна зависеть от реального контракта
  `coverage_analysis`, а не от предположений текущего database-документа.

## MVP-порядок реализации

Рекомендуемый порядок:

1. Создать SQLite-файл в `.pytest-alchemist-artifacts/pytest-alchemist.sqlite`.
2. Реализовать `test_runs`, `tests`, `coverage_artifacts`.
3. Сохранять обычные запуски тестов и пути к stdout/stderr/coverage.
4. Вернуться к схеме нормализованного coverage после реализации контракта
   `coverage_analysis`.

Такой порядок позволяет сначала получить рабочую историю запусков и
сохранение артефактов, а затем проектировать coverage-хранилище на основании
реальных данных.

## Открытые вопросы

- Какой режим per-test coverage будет выбран: coverage.py contexts или
  отдельные запуски тестов?
- Нужно ли хранить `.coverage` SQLite-файл как raw artifact вместе с JSON/XML?
- Нужно ли версионировать конфигурацию coverage, чтобы понимать, с какими
  `source`, `omit` и `include` был собран конкретный запуск?
- Нужно ли сразу поддерживать несколько source roots?
- Как долго хранить старые `test-runs` и когда чистить связанные записи из
  базы?
