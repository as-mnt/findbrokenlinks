# План: утилита поиска битых ссылок (findbrokenlinks)

## Context

Цель — Python-утилита, которая по URL обходит сайт и фиксирует ссылки, открытие которых в браузере не соответствовало бы ожиданиям пользователя: HTTP-ошибки, странные редиректы, "soft 404" сообщения от CMS, сетевые сбои.

Архитектура должна позволять **легко добавлять новые контроли** (без правок ядра), поэтому центральным паттерном выбраны Strategy + Registry — каждый контроль (`Check`) и каждый формат вывода (`Reporter`) живёт в собственном модуле и регистрируется декоратором.

Каталог проекта пуст — реализация делается с нуля. Целевая платформа: Linux, Python 3.11+.

## Зафиксированные требования (ответы пользователя)

- Режимы обхода: page / internal / internal+external — переключаются ключом CLI (`--mode`)
- Без JS: только raw HTML через httpx
- Конкурентность: asyncio + httpx
- Форматы вывода: csv, json, tsv (tabbed), html, markdown, junit-xml, sarif
- robots.txt: уважаем по умолчанию, отключается флагом; rate-limit настраивается через CLI
- Soft-404: оба механизма (regex-паттерны + probing с эталонным 404)
- Подозрительные редиректы: редирект на "/" / home + цепочка >N редиректов (N настраивается)
- Дополнительно к `<a href>` проверяем `<img src>`, `<script src>`, `<link href>`

## Архитектура и применяемые паттерны

- **Strategy** — `Check` и `Reporter` имеют общий ABC и сменные реализации
- **Registry** (декоратор `@register`) — динамическая регистрация контролей и репортеров; добавить новый контроль = создать файл + декоратор, ядро не трогаем
- **Producer–Consumer / Worker Pool** — crawler: `asyncio.Queue` фронтира + пул воркеров
- **Composite** — наборы паттернов soft-404 (встроенные + пользовательский YAML)
- **Factory** — выбор `Reporter` по имени формата из CLI
- **Pipeline** — Fetcher → Extractor → Checks → Aggregator → Reporter

## Структура проекта

```
findbrokenlinks/
├── pyproject.toml                       # deps, console_scripts entry point
├── README.md
├── src/findbrokenlinks/
│   ├── __main__.py                      # python -m findbrokenlinks
│   ├── cli.py                           # argparse + Config
│   ├── config.py                        # @dataclass Config
│   ├── models.py                        # LinkRef, FetchResult, Issue, Finding
│   ├── crawler.py                       # async фронтир + воркеры
│   ├── fetcher.py                       # httpx.AsyncClient + retries + rate limiter
│   ├── rate_limiter.py                  # token-bucket на asyncio
│   ├── robots.py                        # обёртка над urllib.robotparser
│   ├── scope.py                         # фильтр URL по режиму
│   ├── extractors/
│   │   ├── base.py                      # ABC Extractor
│   │   └── html.py                      # BeautifulSoup: <a>, <img>, <script>, <link>
│   ├── checks/                          # ← ключевая точка расширения
│   │   ├── base.py                      # ABC Check + CheckContext + REGISTRY
│   │   ├── http_status.py               # 4xx/5xx
│   │   ├── network_error.py             # DNS/TCP/TLS/timeout
│   │   ├── redirect_to_home.py          # редирект в "/"
│   │   ├── redirect_chain.py            # >N редиректов
│   │   ├── soft_404_pattern.py          # regex по title/h1/тексту
│   │   └── soft_404_probe.py            # сравнение с baseline-404
│   ├── reporters/                       # ← ключевая точка расширения
│   │   ├── base.py                      # ABC Reporter + REGISTRY
│   │   ├── csv_reporter.py
│   │   ├── json_reporter.py
│   │   ├── tsv_reporter.py
│   │   ├── html_reporter.py             # Jinja2 шаблон
│   │   ├── markdown_reporter.py
│   │   ├── junit_reporter.py
│   │   └── sarif_reporter.py
│   ├── patterns/
│   │   └── builtin.yaml                 # soft-404 паттерны для WP, Joomla, Drupal, Bitrix, Tilda, Nginx, Apache
│   └── logging_setup.py
└── tests/
    ├── conftest.py                      # pytest-httpx, Starlette fake-server fixture
    ├── test_extractors.py
    ├── test_checks_*.py                 # по одному файлу на контроль
    ├── test_reporters_*.py
    ├── test_crawler_integration.py      # end-to-end по локальному серверу
    └── fixtures/                        # html-семплы с known issues
```

## Модель данных (`src/findbrokenlinks/models.py`)

```python
@dataclass(frozen=True)
class LinkRef:
    url: str                # абсолютный URL цели
    source_page: str        # страница, где найдена ссылка
    anchor: str | None      # текст ссылки или alt
    tag: str                # 'a' | 'img' | 'script' | 'link'

@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None      # None при сетевой ошибке
    redirect_chain: list[str]
    headers: Mapping[str, str]
    body: str | None
    elapsed_ms: float
    error: str | None       # 'timeout' | 'dns' | 'ssl' | 'connect' | None

@dataclass(frozen=True)
class Issue:
    code: str               # 'HTTP_ERROR', 'REDIRECT_TO_HOME', 'SOFT_404_PATTERN', ...
    severity: Literal['error', 'warning', 'info']
    message: str
    details: dict[str, Any]

@dataclass
class Finding:
    link: LinkRef
    fetch: FetchResult
    issues: list[Issue]     # одна ссылка может проваливать несколько контролей
```

## Интерфейс контроля — ключевая точка расширения

```python
# checks/base.py
class Check(ABC):
    code: ClassVar[str]
    severity: ClassVar[str] = "error"

    @abstractmethod
    def evaluate(self, link: LinkRef, fetch: FetchResult, ctx: CheckContext) -> Issue | None: ...

REGISTRY: dict[str, type[Check]] = {}

def register(cls: type[Check]) -> type[Check]:
    REGISTRY[cls.code] = cls
    return cls
```

`CheckContext` несёт baseline-404 (для probe-чекера), `Config`, базовый домен, скомпилированные паттерны.

**Добавление нового контроля** = новый файл в `checks/`, наследник `Check`, декоратор `@register`. Никаких правок ядра. Включение/выключение: `--enable-checks code1,code2` / `--disable-checks ...`.

## Интерфейс репортера

```python
class Reporter(ABC):
    name: ClassVar[str]            # 'csv', 'json', 'html', ...
    @abstractmethod
    def render(self, findings: list[Finding], out) -> None: ...
```

CLI принимает `--format json,html` → несколько файлов через `--output-dir`.

## Crawler (`crawler.py`)

1. **Seed**: исходный URL (+ опционально sitemap.xml через `--use-sitemap`)
2. **Frontier**: `asyncio.Queue[URL]` + `seen: set[URL]`
3. **Worker pool** (N=10 по умолчанию): корутины `await queue.get()` → `fetcher.get()` → `extractor.extract()`
4. Нормализация URL (lowercase host, drop фрагмента, sort query) — utility в `scope.py`
5. `Scope` по режиму: enqueue для рекурсии / только fetch для проверки / skip
6. Для каждого fetched URL запускаем все включённые `Check.evaluate(...)`, собираем `Finding` если есть issues
7. Aggregator группирует findings по `source_page`

**Rate-limit**: token-bucket внутри `Fetcher`, лимит из `Config.rate_limit_rps`. **robots.txt**: при первом обращении к домену подгружаем и кешируем; `--ignore-robots` отключает.

## Soft-404: оба механизма

- **Probe** (`soft_404_probe.py`): при старте обхода для каждого домена запрашиваем `<scheme>://<host>/__fbl_probe_<random16>__`. Сохраняем `status`, `len(text)`, SHA1 нормализованного текста (без скриптов/стилей/пробелов), `final_url`. Контроль сравнивает каждый 200-ответ: длина ±10% и совпадение хэша/Jaccard ≥ 0.9 → `SOFT_404_PROBE`.
- **Pattern** (`soft_404_pattern.py`): `patterns/builtin.yaml` + опциональный `--patterns user.yaml` (composite). Запись: `{name, regex, target: title|h1|body}`. Совпадение → `SOFT_404_PATTERN` с указанием паттерна.

Пример `builtin.yaml`:
```yaml
- name: wordpress_404
  target: title
  regex: '(?i)^Page not found|Страница не найдена'
- name: bitrix_404
  target: body
  regex: 'Запрашиваемая страница не найдена'
- name: nginx_default_404
  target: body
  regex: '<center><h1>404 Not Found</h1></center>'
```

## CLI

```
findbrokenlinks <URL> [options]

Scope:
  --mode {page,internal,internal+external}   default: internal+external
  --depth N                                  default: 0 (unlimited)
  --use-sitemap                              подсасывать sitemap.xml в очередь

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
  --format fmt[,fmt...]          csv|json|tsv|html|markdown|junit|sarif (default: tsv)
  --output PATH                  default: stdout
  --output-dir DIR               для нескольких форматов: <name>_report.<ext>

Misc:
  -v / --verbose
  --log-file PATH
```

## Поля вывода (одинаковые во всех репортерах)

`source_page`, `link_url`, `final_url`, `anchor`, `tag`, `status`, `redirect_chain`, `issue_codes`, `severity`, `details`.

В HTML-отчёте дополнительно: группировка по `source_page`, цветовая разметка severity, кликабельные ссылки.

## Зависимости

Runtime:
- `httpx[http2]>=0.27` — async HTTP клиент с поддержкой HTTP/2 и редиректов
- `beautifulsoup4>=4.12` — парсинг HTML
- `lxml>=5.0` — быстрый парсер-бэкенд для bs4
- `pyyaml>=6.0` — конфиг паттернов soft-404
- `jinja2>=3.1` — шаблоны для HTML- и Markdown-отчётов
- `rich>=13.0` — прогресс-бар и цветной консольный вывод (опционально, fallback на logging)

Dev:
- `pytest>=8.0`
- `pytest-asyncio>=0.23`
- `pytest-httpx>=0.30` — мокирование httpx-ответов в юнит-тестах
- `starlette>=0.37` + `uvicorn` — локальный тестовый сервер для интеграционных тестов
- `ruff` — линтер/форматтер
- `mypy>=1.10` — статическая типизация

Стандартная библиотека покрывает: `argparse`, `asyncio`, `urllib.robotparser`, `csv`, `json`, `xml.etree.ElementTree` (JUnit), `hashlib`, `dataclasses`.

Console entry point: `findbrokenlinks = findbrokenlinks.cli:main`.

## Верификация

1. **Юнит-тесты** на каждый контроль (`tests/test_checks_*.py`) — `pytest-httpx` мокает ответы; проверяем, что контроль возвращает `Issue` именно в ожидаемых ситуациях и `None` в граничных.
2. **Юнит-тесты репортеров** — рендеринг фиксированного списка `Finding`, snapshot-сравнение.
3. **Интеграционный тест** (`test_crawler_integration.py`) — поднимаем локальный Starlette-сервер с маршрутами:
   - `/ok` → 200 валидный HTML
   - `/missing` → 404
   - `/redirect-chain` → 5 последовательных 302
   - `/soft404-pattern` → 200 со страницей «Страница не найдена»
   - `/redirect-home` → 302 на `/`
   - `/img-broken` → 404 для картинки, ссылающейся со страницы `/ok`

   Запускаем crawler, ассертим итоговый список findings.
4. **Smoke**: `findbrokenlinks https://httpbin.org/links/10/0 --mode page --format tsv` — должен отработать без ошибок.
5. **Тест расширяемости**: добавить тестовый контроль в `tests/test_extension.py`, объявить `@register` класс, убедиться, что он подключается без правок ядра.
