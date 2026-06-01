# Контекст реализации

Снимок проекта на момент завершения первой итерации. Что построено, как это устроено,
как расширять.

## Статус

- ✅ Реализованы все 6 контролей и 7 репортеров из плана
- ✅ Async-краулер с воркер-пулом, token-bucket rate-limit, robots.txt, дедупликация по
  `final_url` после редиректов
- ✅ Ленивый baseline-404 probe на каждый внутренний хост
- ✅ CLI с режимами `page` / `internal` / `internal+external`, выбором форматов,
  `--enable-checks` / `--disable-checks`
- ✅ Makefile с целями для setup / test / lint / типовых запусков
- ✅ 31 тест (юнит + интеграционный e2e на локальном Starlette), все зелёные

Размер кода: ~1560 LOC по `src/findbrokenlinks` + `tests/`.

## Раскладка файлов

```
findbrokenlinks/
├── Makefile                            # setup / test / run-* / clean
├── pyproject.toml
├── docs/
│   ├── task.md                         # исходная задача и Q&A
│   ├── plan.md                         # одобренный план реализации
│   └── context.md                      # этот файл
├── src/findbrokenlinks/
│   ├── __main__.py                     # python -m findbrokenlinks
│   ├── cli.py                          # argparse + Config + multi-format вывод
│   ├── config.py                       # dataclass Config
│   ├── models.py                       # LinkRef / FetchResult / Issue / Finding
│   ├── crawler.py                      # async фронтир + воркеры + probe
│   ├── fetcher.py                      # httpx wrapper, классификация ошибок
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
│   │   ├── base.py                     # Reporter ABC + REGISTRY + ROW_FIELDS + _row_for
│   │   ├── csv_reporter.py
│   │   ├── tsv_reporter.py
│   │   ├── json_reporter.py
│   │   ├── html_reporter.py
│   │   ├── markdown_reporter.py
│   │   ├── junit_reporter.py
│   │   └── sarif_reporter.py
│   └── patterns/builtin.yaml           # 12 soft-404 паттернов (RU/EN, WP/Drupal/Bitrix/…)
└── tests/
    ├── conftest.py                     # Starlette fake-server + uvicorn в потоке
    ├── test_scope.py
    ├── test_extractor.py
    ├── test_checks.py                  # по контролю
    ├── test_reporters.py
    ├── test_extension.py               # проверяет расширяемость через @register
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
      │ ──► Fetcher ──► httpx.AsyncClient (rate limited, robots-aware)
      │      │
      │      ▼
      │   FetchResult
      │      │
      │      ▼
      │   HTMLExtractor ──► LinkRef[]
      │      │
      │      ▼
      │   queue.put(new URLs)
      ▼
  CheckContext ──► [Check].evaluate(link, fetch, ctx) ──► Issue?
                                                 │
                                                 ▼
                                            Finding[]
                                                 │
                                                 ▼
                                          Reporter.render() ──► str
```

Краулер дедуплицирует фетчи (`state.fetched[url]`) и извлечения тела (`state.extracted_from`).
Тело, полученное по редиректу, атрибутируется `final_url` — это предотвращает дублирование
ссылок при перекрёстных путях к одной странице.

### Применяемые паттерны

- **Strategy + Registry** — `Check` и `Reporter` (`@register` декоратор → словарь `REGISTRY`)
- **Producer–Consumer** — `asyncio.Queue` + N воркеров
- **Composite** — паттерны soft-404 (встроенные + пользовательский YAML)
- **Factory** — `get_reporter(name)` по строке формата
- **Pipeline** — `Fetcher → Extractor → Checks → Reporter`

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
  --use-sitemap                              подсасывать /sitemap.xml в очередь

Network:
  --rate-limit RPS               default: 5
  --concurrency N                default: 10
  --timeout SECONDS              default: 15
  --max-redirects N              default: 10
  --user-agent UA
  --ignore-robots

Checks:
  --enable-checks code1,code2
  --disable-checks code1,code2
  --redirect-chain-threshold N   default: 3
  --patterns PATH                user yaml для soft-404
  --no-soft404-probe

Output:
  --format fmt[,fmt...]          csv|tsv|json|html|markdown|junit|sarif (default: tsv)
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
| `make run URL=…` | Дефолтный обход |
| `make run-page URL=…` | Только одна страница |
| `make run-internal URL=…` | Только внутренние |
| `make run-all URL=…` | Internal + проверка внешних |
| `make run-html URL=…` | HTML-отчёт |
| `make run-json URL=…` | JSON-отчёт |
| `make run-multi URL=…` | csv/json/html/markdown одновременно |
| `make smoke` | Быстрая проверка example.com |
| `make clean` | Снести venv, кеши, отчёты |

Override-переменные: `URL=…`, `RATE=…`, `OUT_DIR=…`.

## Что осталось вне первой итерации

Намеренно не вошло — добавить, если потребуется:

- JS-рендеринг через Playwright (отказались на этапе планирования)
- Meta-refresh / JS-redirect детекция (отказались)
- Возобновляемый обход (persist queue → disk)
- Авторизация (cookie / basic / OAuth)
- Параллельная проверка нескольких сайтов в одном запуске
- WebSocket / streaming прогресс для длинных обходов
