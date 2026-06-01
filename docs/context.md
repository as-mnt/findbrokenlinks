# Контекст реализации

Снимок проекта. Что построено, как это устроено, как расширять.

## Статус

- ✅ Все 6 контролей и 8 репортеров (`csv`, `tsv`, `json`, `jsonl`, `html`, `markdown`, `junit`, `sarif`)
- ✅ Async-краулер с воркер-пулом, token-bucket rate-limit, robots.txt, дедупликация по
  `final_url` после редиректов
- ✅ Ленивый baseline-404 probe на каждый внутренний хост
- ✅ Streaming-фетчер: бинарные ответы (PDF/архивы/видео) **не качаются вовсе**, текстовые
  читаются чанками до `--max-body-bytes` (default 1 MB)
- ✅ Streaming-отчёт: при выборе одного streamable формата (`csv` / `tsv` / `jsonl`) находки
  пишутся в файл **по мере появления** — можно `tail -f` во время обхода
- ✅ CLI с режимами `page` / `internal` / `internal+external`, выбором форматов,
  `--enable-checks` / `--disable-checks`, `--max-body-bytes`
- ✅ Makefile с целями для setup / test / lint / типовых запусков (включая `run-jsonl` для стриминга)
- ✅ 38 тестов (юнит + интеграционные на локальном Starlette), все зелёные
- ✅ GitHub Actions CI: Python 3.11/3.12/3.13 + ruff + mypy
- ✅ Опубликовано: https://github.com/as-mnt/findbrokenlinks

Размер кода: ~2480 LOC по `src/findbrokenlinks` + `tests/`.

## Раскладка файлов

```
findbrokenlinks/
├── .github/workflows/ci.yml            # GitHub Actions: тесты + lint
├── .gitignore
├── LICENSE                             # MIT
├── Makefile                            # setup / test / run-* / clean
├── README.md
├── pyproject.toml
├── docs/
│   ├── task.md                         # исходная задача и Q&A
│   ├── plan.md                         # одобренный план реализации
│   └── context.md                      # этот файл
├── src/findbrokenlinks/
│   ├── __main__.py                     # python -m findbrokenlinks
│   ├── cli.py                          # argparse + Config + batch/streaming пути
│   ├── config.py                       # dataclass Config
│   ├── models.py                       # LinkRef / FetchResult / Issue / Finding
│   ├── crawler.py                      # async фронтир + воркеры + probe + on_finding
│   ├── fetcher.py                      # httpx streaming, классификация ошибок, body cap
│   ├── rate_limiter.py                 # token bucket, NoopLimiter
│   ├── robots.py                       # async-обёртка над urllib.robotparser
│   ├── scope.py                        # нормализация URL и фильтр по режиму
│   ├── extractors/
│   │   ├── base.py                     # ABC Extractor
│   │   └── html.py                     # bs4: <a>/<img>/<script>/<link> + <base href>
│   ├── checks/                         # ← точка расширения
│   │   ├── base.py                     # Check ABC + REGISTRY + @register + active_checks
│   │   ├── http_status.py
│   │   ├── network_error.py
│   │   ├── redirect_to_home.py
│   │   ├── redirect_chain.py
│   │   ├── soft_404_pattern.py         # + load_patterns(extra)
│   │   └── soft_404_probe.py
│   ├── reporters/                      # ← точка расширения
│   │   ├── base.py                     # Reporter ABC + REGISTRY + streaming API
│   │   ├── csv_reporter.py             # streaming
│   │   ├── tsv_reporter.py             # streaming
│   │   ├── json_reporter.py            # batch
│   │   ├── jsonlines_reporter.py       # streaming (NDJSON)
│   │   ├── html_reporter.py            # batch (группировка по source_page)
│   │   ├── markdown_reporter.py        # batch
│   │   ├── junit_reporter.py           # batch
│   │   └── sarif_reporter.py           # batch
│   └── patterns/builtin.yaml           # 12 soft-404 паттернов (RU/EN, WP/Drupal/Bitrix/…)
└── tests/
    ├── conftest.py                     # Starlette fake-server (uvicorn в потоке)
    ├── test_scope.py
    ├── test_extractor.py
    ├── test_checks.py
    ├── test_reporters.py
    ├── test_fetcher_streaming.py       # PDF не качается, HTML обрезается по cap
    ├── test_streaming.py               # on_finding callback + JSONL + CLI streaming
    ├── test_extension.py               # доказывает расширяемость через @register
    └── test_crawler_integration.py     # end-to-end по локальному серверу
```

## Архитектура и потоки данных

```
       ┌──────────┐
seed → │  Config  │
       └────┬─────┘
            ▼
   ┌─────────────────┐         ┌──────────┐
   │     Crawler     │◄────────┤  Scope   │ filter (mode/host)
   │ (worker pool)   │         └──────────┘
   └──┬──────────────┘
      │ ──► Fetcher ──► httpx.AsyncClient.stream() — rate-limited, robots-aware
      │      │           (бинарные ответы не читаются; текст до max_body_bytes)
      │      ▼
      │   FetchResult ──► state.register_fetch() ──► flush pending LinkRefs ──┐
      │      │                                                                │
      │      ▼                                                                │
      │   HTMLExtractor (если расширяем + текстовый body)                     │
      │      │                                                                │
      │      ▼                                                                │
      │   LinkRef ──► state.register_link() ──► если target уже зафетчен ──► [Check].evaluate()
      │                                          иначе → pending_links                │
      │                                                                               ▼
      └─► queue.put(новые URL)                                              Issue? → Finding
                                                                                     │
                                                                       ┌─────────────┴───────────┐
                                                                       ▼                         ▼
                                                          state.findings (для batch)    on_finding(finding)
                                                                       │                         │
                                                                       ▼                         ▼
                                                          Reporter.render() (HTML/MD/…)  Reporter.stream_append()
                                                                                          (CSV/TSV/JSONL → файл)
```

**Ключевые инварианты:**

- Тело принадлежит `final_url`, а не запрошенному `url` — атрибутируем ссылки `final_url` и
  дедуплицируем через `extracted_from`, чтобы одну и ту же страницу, доступную разными путями,
  не парсить дважды.
- `pending_links[target_url]` копит LinkRef'ы, чьи цели ещё не зафетчены. При завершении
  фетча — все накопленные ссылки немедленно прогоняются через контроли и эмитятся.
- `on_finding` — sync-callback; стриминговый репортер пишет в файл с `flush()` после каждой
  находки, поэтому `tail -f` видит данные сразу.

### Применяемые паттерны

- **Strategy + Registry** — `Check` и `Reporter` (`@register` декоратор → словарь `REGISTRY`)
- **Producer–Consumer** — `asyncio.Queue` + N воркеров
- **Composite** — паттерны soft-404 (встроенные + пользовательский YAML)
- **Factory** — `get_reporter(name)` по строке формата
- **Pipeline** — `Fetcher → Extractor → Checks → Reporter`
- **Observer** — `on_finding` callback для стриминговой записи отчёта

## Streaming vs batch: какой репортер какой

| Формат | Streaming | Почему |
|---|---|---|
| `csv` | ✅ | Header + строка на находку — независимые единицы |
| `tsv` | ✅ | То же, с табами |
| `jsonl` | ✅ | Newline-delimited JSON — одна находка = одна строка |
| `json` | ❌ | Единый документ с `summary` и массивом — нужны все находки |
| `html` | ❌ | Группировка по `source_page`, нужны все |
| `markdown` | ❌ | То же |
| `junit` | ❌ | Агрегированные `<testsuite tests=N failures=N>` |
| `sarif` | ❌ | Единый run-объект |

CLI автоматически выбирает streaming-путь, если выбран **один** streamable формат. Multi-format
(`--format csv,html`) всегда идёт по batch-пути.

## Как добавить новый контроль

Никаких правок ядра. Создать файл `src/findbrokenlinks/checks/my_check.py`:

```python
from findbrokenlinks.checks.base import Check, CheckContext, register
from findbrokenlinks.models import FetchResult, Issue, LinkRef


@register
class MyCheck(Check):
    code = "MY_CODE"
    severity = "warning"  # или "error" / "info"

    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None:
        if ...:
            return Issue(self.code, self.severity, "human-readable message", {"k": "v"})
        return None
```

Добавить импорт в `checks/__init__.py` (иначе декоратор не выполнится). Готово —
контроль участвует во всех обходах, включается/отключается через
`--enable-checks` / `--disable-checks`.

Тест расширяемости: `tests/test_extension.py` показывает, что регистрация и работа
проходят без правок ядра.

## Как добавить новый формат отчёта

`src/findbrokenlinks/reporters/my_reporter.py`:

```python
from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


@register
class MyReporter(Reporter):
    name = "myfmt"
    file_ext = "myx"

    def render(self, findings: list[Finding]) -> str:
        ...
```

Добавить импорт в `reporters/__init__.py`. CLI автоматически примет `--format myfmt`.

### Стриминговый репортер (опционально)

Если формат может писать инкрементально (по находке), выставить
`streaming: ClassVar[bool] = True` и реализовать `stream_start(out)`,
`stream_append(finding, out)`, `stream_finish(out)`. CLI автоматически
переключится на потоковую запись, если выбран один такой формат.

Примеры: `csv_reporter.py`, `tsv_reporter.py`, `jsonlines_reporter.py`. Стандартный паттерн —
писать в `out` и сразу делать `out.flush()`, чтобы внешний наблюдатель (`tail -f`) видел данные.

## Как добавить пользовательские soft-404 паттерны

YAML того же формата, что `patterns/builtin.yaml`:

```yaml
- name: my_cms_404
  target: title           # title | h1 | body
  regex: '(?i)not here'
```

Передаётся через `--patterns path/to/my.yaml`. Паттерны объединяются с встроенными
(Composite).

## CLI: справка

```
findbrokenlinks <URL> [options]

Scope:
  --mode {page,internal,internal+external}   default: internal+external
  --depth N                                  default: 0 (unlimited)
  --max-pages N                              default: 10000 (0 = unlimited);
                                             страховка от безграничных URL-пространств
                                             (session-id, календари, search-facets)
  --use-sitemap                              подсасывать /sitemap.xml в очередь

Network:
  --rate-limit RPS               default: 5
  --concurrency N                default: 10
  --timeout SECONDS              default: 15
  --max-redirects N              default: 10
  --max-body-bytes N             default: 1048576 (1 MB) — cap на текстовые тела;
                                 бинарные ответы (PDF, изображения, архивы) не качаются вовсе
  --user-agent UA
  --ignore-robots

Checks:
  --enable-checks code1,code2
  --disable-checks code1,code2
  --redirect-chain-threshold N   default: 3
  --patterns PATH                user yaml для soft-404
  --no-soft404-probe

Output:
  --format fmt[,fmt...]          csv|tsv|json|jsonl|html|markdown|junit|sarif (default: tsv)
                                 streaming: csv, tsv, jsonl — пишут по мере обхода
  --output PATH                  default: stdout (один формат)
  --output-dir DIR               для нескольких форматов: report.<ext>

Misc:
  -v / --verbose
  --log-file PATH
```

Exit code: `1` если есть `error`-уровня находки, иначе `0` — удобно для CI.

## Команды Makefile

| Цель | Назначение |
|---|---|
| `make help` | Список целей |
| `make install` / `install-dev` | venv + runtime / +dev зависимости |
| `make test` / `test-unit` / `test-integration` | Тесты |
| `make lint` / `typecheck` | ruff / mypy |
| `make check` | **lint + typecheck + test одной командой** — повторяет CI-пайплайн локально, запускать перед `git push` |
| `make run URL=…` | Дефолтный обход |
| `make run-page URL=…` | Только одна страница |
| `make run-internal URL=…` | Только внутренние |
| `make run-all URL=…` | Internal + проверка внешних |
| `make run-html URL=…` | HTML-отчёт (batch — пишется в конце) |
| `make run-json URL=…` | JSON-отчёт (batch — пишется в конце) |
| `make run-jsonl URL=…` | **Streaming JSONL** — `tail -f`-able во время обхода |
| `make run-multi URL=…` | csv/json/html/markdown одновременно |
| `make smoke` | Быстрая проверка example.com |
| `make clean` | Снести venv, кеши, отчёты |

Override-переменные: `URL=…`, `RATE=…`, `OUT_DIR=…`.

## История изменений после v0.1

- **Streaming fetcher + `--max-body-bytes`** (`706441d`) — `httpx.stream()` вместо `get()`;
  бинарные тела не качаются, текстовые читаются чанками с верхней границей.
- **Streaming report** (`d453d1b`) — `on_finding` callback в `crawl()`; streaming API у
  `Reporter`; новый формат `jsonl`; CLI авто-стримит для одного streamable формата.
- **Makefile run-jsonl** (`37f8a62`) — отдельный таргет для стриминга JSONL, с пояснением в
  комментарии когда выбирать его вместо `run-json`.
- **Cycle tests + `--max-pages`** — тесты `tests/test_cycles.py` фиксируют корректную
  обработку link-циклов / self-loop / redirect-loop. Добавлен `--max-pages` (default 10000)
  как safety net против безграничных URL-пространств; работает на уровне `enqueue()`.

## Что осталось вне первой итерации

Намеренно не вошло — добавить, если потребуется:

- JS-рендеринг через Playwright (отказались на этапе планирования)
- Meta-refresh / JS-redirect детекция
- Возобновляемый обход (persist queue → disk)
- Авторизация (cookie / basic / OAuth)
- Параллельная проверка нескольких сайтов в одном запуске
- Прогресс-метрика (scanned / found) в реальном времени — пока пишем httpx-логи в stderr
