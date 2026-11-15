[English](README.en.md) | **Русский**

# Antigravity Operator

> Автономный агент для организации медиатеки Plex/Jellyfin ([TRaSH Guides](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/)), ремукса дорожек и аппаратного сжатия AV1/HEVC в Docker.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Runtime: Docker Engine](https://img.shields.io/badge/Runtime-Docker%20Engine-2496ED?logo=docker&logoColor=white)](docker/Dockerfile)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#аппаратное-ускорение-gpu)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-Main_Repo-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/Retr0xCC/antigravity-operator)
[![GitHub](https://img.shields.io/badge/GitHub-Mirror-181717?logo=github&logoColor=white)](https://github.com/Retr0xCC/antigravity-operator)

---

## Предыстория и предназначение

### Проблема домашних медиасерверов
Любой владелец домашнего кинотеатра на базе **Plex**, **Jellyfin** или **Emby** неизбежно сталкивается с конфликтом двух миров:
1. **Медиасерверы требуют строгой структуры:** для автоматического сопоставления постеров, описаний и актеров файлы должны быть разложены по строгим каноническим путям, например:
   `Movies/The Matrix (1999)/The Matrix (1999).mkv` или `TV/Frieren (2023)/Season 01/Frieren S01E01.mkv`.
2. **Торрент-клиенты требуют неизменности:** скачанные файлы в `Downloads` должны оставаться с оригинальными именами и путями, иначе хэш раздачи ломается, сидинг останавливается, а рейтинг на трекере падает.

### Решение: Атомарные жесткие ссылки (TRaSH Guides)
Стандарт сообщества — методология [TRaSH Guides: Hardlinks and Instant Moves](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/).

Если папка загрузок (`Downloads`) и медиатека (`Media`) находятся на **одном физическом разделе диска**, файлы не копируются и не перемещаются. Вместо этого создаются жесткие ссылки (`os.link`): второй указатель файловой системы на тот же самый инод. 
* Место на диске **не дублируется** (Zero-Copy).
* Торрент продолжает непрерывно раздаваться в `Downloads`.
* Медиасервер получает идеальную, чистую структуру в `Media`.

```text
       Физический файл на диске (ext4, Inode #482910)
                      ▲                ▲
                      │                │
           [Жесткая ссылка 1]    [Жесткая ссылка 2]
         /storage/Downloads/      /storage/Media/Movies/
         The.Matrix.1999.BDRip    The Matrix (1999)/The Matrix (1999).mkv
         (Раздача на трекере)     (Каталог Plex / Jellyfin)
```

### Зачем здесь ИИ-агент?
Торрент-раздачи редко приходят в идеальном виде. Часто это хаос:
* Транслит или японские ромадзи в названиях (`Koukaku Kidoutai (2026) [WEB-DL 1080p]`).
* Внешние дорожки озвучек (`.mka`) и субтитры (`.ass`) лежат отдельными файлами вперемешку со шрифтами (`.ttf`).
* Традиционные утилиты (Sonarr, Radarr) работают на жестких регулярных выражениях и пасуют на нестандартных релизах, сериалах с несколькими озвучками или аудиокнигах.

**ИИ-агент Antigravity (`agy`) берет рутину на себя:**
1. Разбирает неструктурированные названия релизов и сопоставляет их с каноническими именами в IMDb/TMDb/Wikipedia.
2. Анализирует состав раздачи: понимает, какие внешние аудиодорожки и субтитры к какой серии относятся, и с помощью утилиты `muxpress` собирает их в монолитный MKV-контейнер без потери качества.
3. Мгновенно формирует структуру библиотеки TRaSH Guides через `os.link`.

---

## Почему Docker Engine вместо Docker Sandboxes (SBX)

Изначально для изоляции рассматривался Docker Sandboxes (`sbx`). Однако отказ от SBX в пользу классического **Docker Engine** — осознанное инженерное решение:

* **Прямой доступ к GPU (Hardware Passthrough):** SBX изолирует процессы внутри microVM, где отсутствует аппаратный проброс символьных устройств хоста. Сжатие видео в **AV1** и **HEVC** на видеокартах AMD (Radeon RX 7000 через `/dev/dri`) или NVIDIA (CUDA NVENC) в SBX физически невозможно. Docker Engine пробрасывает GPU напрямую без виртуализационного оверхеда.
* **Сетевая изоляция на уровне ядра взамен SBX:** Для замены встроенной изоляции Docker Sandboxes контейнер запускается с параметром `--network=none` (интерфейс `eth0` отсутствует, прямой сетевой доступ исключен на уровне ядра). Исходящий трафик направляется исключительно через эфемерный Unix Domain Socket во встроенный прокси-сервер ([core/proxy.py](core/proxy.py)). Он блокирует доступ контейнера к приватным подсетям локальной сети (`192.168.x.x`, `10.x.x.x`, роутеру и хосту) и пропускает запросы только к Google API и базам метаданных без необходимости в правах root или iptables.
* **Производительность ввода-вывода (Zero-Copy):** Прямое монтирование единого дискового раздела `/storage:rw` позволяет ядру Linux создавать жесткие ссылки `os.link()` за миллисекунды.

---

## Архитектура безопасности

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                           Хост                              │
 │                                                             │
 │   Защищенные ресурсы (Недоступны контейнеру):               │
 │   - Домашний каталог (~/.ssh, ~/.gnupg, ~/.docker)          │
 │   - Системный диск (/) и Docker Socket                      │
 │                                                             │
 │   Локальный allowlist-прокси (раннер operate):              │
 │   - Разрешено: Google Gemini API, IMDb, TMDb, Wikipedia     │
 │   - Заблокировано: Домашняя сеть LAN (192.168.x.x), хост    │
 └───────────────────────────────┬─────────────────────────────┘
                                 │ HTTP CONNECT туннель
                                 │ host.docker.internal:<порт>
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │               Песочница Antigravity Operator                │
 │               (База: antigravity-sbx-patched)               │
 │                                                             │
 │   - Пользователь: 'agent' (UID 1000, no-new-privileges)     │
 │   - Запрет сырых сокетов: --cap-drop=NET_RAW                │
 │   - Быстрый RAM-диск: --tmpfs=/tmp:rw,size=4g (чистый диск) │
 │   - Ускоритель: /dev/dri/renderD128 (AMD VA-API AV1/HEVC)   │
 │   - Лимиты: memory=8g, cpus=4, pids-limit=4096, Tini init   │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 │  os.link(src, dst)
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │           Физический раздел хранилища (/storage)            │
 │                                                             │
 │   /storage/Downloads/ ──[Hardlink (same inode)]──► /storage/│
 │   (Торрент раздаётся)                                Media/ │
 └─────────────────────────────────────────────────────────────┘
```

---

## Быстрый старт

### 1. Проверка хост-окружения
```bash
bin/operate doctor
```
Проверяет наличие Docker Engine, распознает видеокарту хоста (AMD Radeon VA-API, NVIDIA NVENC), поддержку аппаратного **AV1**, статус авторизации в Gemini и рецепты.

### 2. Авторизация в Google Antigravity
Оператор полностью автономен и **не требует наличия Antigravity на хосте**. Настройки, OAuth-токены и API-ключи сохраняются в общей директории `~/.gemini` (монтируемой в `/home/agent/.gemini` контейнера):
* **Настройка авторизации (Google OAuth или API-ключ):**
  ```bash
  bin/operate login
  ```
  Позволяет выполнить вход через Google OAuth или сохранить ключ Gemini API. Ключ/токен сохраняется в `~/.gemini` и автоматически подхватывается всеми последующими запусками.
* **Быстрое сохранение API-ключа одной командой:**
  ```bash
  bin/operate login --key="AIzaSy..."
  ```
* **Или через переменные окружения:**
  ```bash
  export GEMINI_API_KEY="AIzaSy..."
  # или через флаг запуска: bin/operate run ... --api-key="AIzaSy..."
  ```
* **Проверка статуса или выход:**
  ```bash
  bin/operate login --status
  bin/operate login --logout
  ```

### 3. Запуск рецептов

* **Организация медиатеки (Zero-Copy Hardlink):**
  Мгновенно связывает фильм или сериал из `Downloads` в `Media` с поиском канонического названия на IMDb:
  ```bash
  bin/operate run media-link /mnt/storage/Downloads/The.Matrix.1999 /mnt/storage/Media/Movies
  ```

* **Сборка дорожек и шрифтов в монолитный MKV (Remux):**
  Объединяет видео, внешние дорожки озвучек (`.mka`), субтитры (`.ass`) и вложенные шрифты в единый файл без пережатия видеопотока:
  ```bash
  bin/operate run media-remux /mnt/storage/Downloads/Attack.on.Titan /mnt/storage/Media/TV
  ```

* **Аппаратное сжатие в AV1 на AMD Radeon RX 7700 XT:**
  Автоматически задействует аппаратный энкодер AV1 (`av1_vaapi`) с защитой Rollback Guard (если сжатый файл оказался больше оригинала, временный файл удаляется):
  ```bash
  bin/operate run media-compress /mnt/storage/Media/TV/Frieren --codec av1 --quality 28
  ```

* **Офлайн-режим (`--offline`):**
  Полностью отключает сеть (`--network=none`) для детерминированных задач:
  ```bash
  bin/operate run media-link /mnt/storage/Downloads/Series /mnt/storage/Media/TV --offline
  ```

### 4. Сборка контейнера
Образ собирается downstream от базового `ghcr.io/retr0xcc/antigravity-sbx-patched:latest`:
* **Удаленно:** через встроенный GitHub Actions воркфлоу [.github/workflows/build-and-publish.yml](.github/workflows/build-and-publish.yml) (образ автоматически публикуется в GHCR).
* **Локально:** при необходимости внесения правок:
  ```bash
  bin/operate build
  ```

---

## Доступные рецепты

| Рецепт | Назначение | Ресурсы | Время |
| :--- | :--- | :--- | :--- |
| **`media-link`** | Организация структуры TRaSH Guides через Zero-Copy Hardlinks | 0% GPU, 0% CPU | ~5–10 сек |
| **`media-remux`** | Lossless упаковка дорожек, субтитров и шрифтов в единый MKV (`-c copy`) | Без пережатия | ~20–40 сек |
| **`media-compress`**| Аппаратное AV1 / HEVC сжатие тяжелых релизов с защитой Rollback | GPU (AMD VA-API / NVENC) | Зависит от GPU |
| **`media-pipeline`**| Комплексный конвейер (Link + Remux + Compress) | Настраиваемый | Полный цикл |

---

## Справочник параметров CLI

```text
operate run <recipe> <source> [destination] [параметры]
```

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `recipe` | — | Имя рецепта (`media-link`, `media-remux`, `media-compress`, `media-pipeline`) |
| `source` | — | Исходная папка в `Downloads` или `Media` |
| `destination` / `-d` | Автовыбор | Целевая папка библиотеки (`Movies`, `TV`, `Books`) |
| `--codec` | `auto` | Целевой видеокодек: `auto` (AV1 для RDNA 3/Ada, HEVC для старых), `av1`, `hevc`, `h264` |
| `--backend` | `auto` | Бэкенд энкодера: `auto` (AMD/Intel `vaapi`, NVIDIA `nvenc`, CPU `software`) |
| `--device` | Автовыбор | Путь к DRI render-ноде (например `/dev/dri/renderD128`) |
| `-q`, `--quality` | `28` | Качество сжатия (CQP global_quality для VA-API, QP для NVENC, CRF для CPU) |
| `--preset` | `p6` | Пресет скорости/качества кодирования |
| `--remux` | `false` | Упаковать внешние аудиодорожки, сабы и шрифты в единый `.mkv` |
| `--compress` | `false` | Включить аппаратное сжатие видеопотока |
| `--force` | `false` | Принудительно сжать, даже если видео уже в целевом кодеке |
| `--max-bitrate` | — | Порог битрейта в kbps (например `4500`): пережимать только релизы выше порога |
| `--offline` | `false` | Полный офлайн без сетевых интерфейсов (`--network=none`, офлайн-парсинг) |
| `--no-proxy` | `false` | Отключить встроенный allowlist-прокси и дать прямой сетевой доступ |
| `--api-key` | `env` | Ключ Gemini API (альтернатива входу через `bin/operate login`) |
| `--dry-run` | `false` | Симуляция: запуск агента в read-only режиме (`/storage:ro`) для вывода плана |
| `--auto` | `false` | Автономный запуск без интерактивных подтверждений |

---

## Аппаратное ускорение (GPU)

* **AMD Radeon:** RX 7000 Series (RDNA 3 / Navi 3x, включая Radeon RX 7700 XT) с поддержкой **AV1** (`av1_vaapi`) и **HEVC** (`hevc_vaapi`) через Mesa VA-API на `/dev/dri/renderD128`.
* **NVIDIA:** GeForce GTX 10xx, RTX 20xx/30xx/40xx с драйвером NVIDIA и NVIDIA Container Toolkit.
* **Intel:** Arc / Iris Xe через QuickSync / VA-API.

> [!NOTE]
> Тестирование и профилирование проводились на **AMD Radeon RX 7700 XT** (Linux, Mesa VA-API). Поддержка NVIDIA и Intel заложена в архитектуру и покрыта тестами генерации команд, но на физическом оборудовании NVIDIA/Intel код не проверялся из-за отсутствия карт в наличии.

---

## Лицензия и отказ от ответственности

* Исходный код распространяется под лицензией **[MIT](LICENSE)** (© 2026 Retr0xCC).
* **Disclaimer**: Это независимый проект сообщества. Он не связан, не спонсируется и не одобрен компаниями Google LLC или Docker, Inc. «Google Antigravity» является товарным знаком Google LLC. «Docker» является товарным знаком Docker, Inc.
