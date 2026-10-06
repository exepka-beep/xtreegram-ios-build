# XTree Gram — iOS build

Собирает **unsigned `.ipa`** клиента XTree Gram из upstream Telegram-iOS прямо в GitHub Actions.
Подписи нет намеренно: `.ipa` подписывается при установке вашим Apple ID (Sideloadly / AltStore / 3uTools).

Готовый клиент подключается **только к нашему серверу** (`2.27.200.203:2398`, DC 2).

## Почему патч, а не форк

Telegram-iOS — это Bazel-проект на десятки тысяч файлов. Держать форк дорого: каждая правка
превращается в конфликт при обновлении. Здесь лежит только дифф, а сам исходник клонируется
на запинованном коммите — поэтому сборка воспроизводима, а обновление upstream это одна строка.

| Файл | Что делает |
| --- | --- |
| `.github/workflows/build-unsigned-ipa.yml` | Весь конвейер: клон upstream → патч → Xcode → сборка → чистка → zip |
| `scripts/apply_mods.sh` | Накладывает патч (сначала `--check`, чтобы устаревший патч падал громко) |
| `scripts/slim_ipa.sh` | Выкидывает лишние расширения, локали, символы |
| `patches/0001-xtreegram-branding-and-server.patch` | Брендинг + адрес сервера |

## Что меняет патч

Ровно два файла:

**`submodules/TelegramCore/Sources/Network/Network.swift`**
- `seedAddressList` заменён на наш DC 2 → `2.27.200.203`
- порт `443` → `2398`
- убран `if testingEnvironment`, который уводил на тестовые ДЦ Telegram

Сид-лист — это только бутстрап: после первого `help.getConfig` сервер сам отдаёт клиенту свой
список адресов, поэтому в продовые ДЦ Telegram клиент не уходит.

**`Telegram/BUILD`**
- `CFBundleDisplayName` / `CFBundleName` → `Xtreegram`
- URL-схемы `telegram` / `tg` / `tonsite` → `xtreegram` / `xtreegram-compat` / `xtreegram-site`

## Как собрать

1. Actions → **Build XTree Gram Unsigned IPA** → *Run workflow*.
2. Первая сборка идёт **60–90 минут** (Bazel тянет webrtc, tgcalls, td и компилирует их).
   Последующие — быстрее за счёт кэша Bazel.
3. По окончании скачать артефакт **`Xtreegram-unsigned-ipa-<N>`**.

Локально (нужен macOS + Xcode) то же самое делается так:

```sh
git clone https://github.com/TelegramMessenger/Telegram-iOS.git src
git -C src checkout 6ad963e5b62d354da79040f388ae2b9132fb17b8
git -C src submodule update --init --recursive
./scripts/apply_mods.sh "$PWD/src"
```

## Установка на iPhone

`.ipa` не подписан, поэтому:

1. Установить **Sideloadly** (или AltStore) на компьютер.
2. Подключить iPhone, перетащить `.ipa`, ввести обычный Apple ID.
3. На телефоне: *Настройки → Основные → VPN и управление устройством* → доверять профилю.

**Бесплатный Apple ID = подпись живёт 7 дней**, потом приложение надо переподписать. Платный
Developer Account (99 $/год) даёт год и не требует переподписки.

## Про минуты GitHub Actions

macOS-раннеры тарифицируются **×10**. Бесплатные 2000 минут/мес = **200 macOS-минут**,
а сборка съедает 60–90 — то есть 2–3 прогона в месяц. **Публичный репозиторий — безлимит.**
Секретов здесь нет: в патче только брендинг и адрес сервера, который и так известен по DNS.

## Обновление upstream

`UPSTREAM_REF` в workflow и патч жёстко связаны. При обновлении:

1. поднять `UPSTREAM_REF` до нового коммита,
2. локально прогнать `./scripts/apply_mods.sh <src>` — он скажет, если патч не ложится,
3. пересобрать патч под новый контекст (`git diff`), закоммитить оба изменения вместе.

## Что вырезано из `.ipa`

Расширения `Watch`, `Widget`, `BroadcastUpload`, `Share` и все локали кроме `Base, en, ru` —
чтобы архив был меньше и надёжнее подписывался бесплатным Apple ID. Список правится переменными
`IPA_DROP_PLUGINS` и `IPA_KEEP_LOCALES` в workflow.

Сборка только под **arm64** (реальные устройства). Для симулятора нужна отдельная конфигурация.
