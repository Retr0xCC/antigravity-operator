[English](README.en.md) | **Русский**

# Antigravity Operator

> Автономный Headless-раннер для ИИ-агентов: интеллектуальная организация медиатеки (Plex / Jellyfin), Remux и аппаратное сжатие **AV1** (AMD RDNA 3 / RX 7700 XT) и **HEVC** (AMD VA-API / NVIDIA NVENC) на базе изолированной песочницы Docker Sandboxes (SBX) и Docker Engine.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Docker: Sandboxes & Engine](https://img.shields.io/badge/Runtime-SBX%20%7C%20Docker-2496ED?logo=docker&logoColor=white)](docker/Dockerfile)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#аппаратное-сжатие-gpu)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Codeberg](https://img.shields.io/badge/Codeberg-Main_Repo-2185D0?logo=codeberg&logoColor=white)](https://codeberg.org/Retr0xCC/antigravity-operator)
[![GitHub](https://img.shields.io/badge/GitHub-Mirror-181717?logo=github&logoColor=white)](https://github.com/Retr0xCC/antigravity-operator)

---

## Обзор

При автономной пакетной обработке медиафайлов (сотни гигабайт видео, внешние аудиодорожки, субтитры и шрифты) автономному ИИ-агенту требуются права на запуск системных утилит (`ffmpeg`, `ffprobe`, `mkvmerge`) и интенсивные операции с файловой системой.

Прямой запуск такого агента на хосте чреват неконтролируемым расходом системных ресурсов (утечки памяти, процессы-зомби, перегрузка CPU) и риском компрометации хостовой системы (домашний каталог пользователя, ключи SSH, системные конфиги).

**Antigravity Operator** решает эту задачу, изолируя автономного агента Antigravity (`agy --dangerously-skip-permissions`) внутри контролируемой песочницы:

* **Изоляция хоста от агента:** Хостовая ОС, системные каталоги, домашняя папка пользователя (`~/.ssh`, `~/.docker`) и Docker socket полностью скрыты от агента. Ресурсы жестко лимитированы (ОЗУ, CPU, лимит PID, Tini-инициализатор против процессов-зомби).
* **Необходимый компромисс монтирования хранилища:** Для работы Zero-Copy жёстких ссылок (`os.link()`) без ошибки ядра `EXDEV` исходные загрузки (`Downloads`) и медиатека (`Media`) физически обязаны находиться на одном разделе и монтироваться в контейнер общим корнем (`/storage:rw`). Это осознанный архитектурный компромисс: контейнерная изоляция защищает хост, но внутри хранилища безопасность данных опирается на строгий регламент агента и атомарность инструментов.
* **Атомарность и защита от повреждения данных:**
  - **Zero-Copy Hardlinks:** Исходные файлы в `Downloads` никогда не перемещаются, не переименовываются и не изменяются, сохраняя непрерывную раздачу торрентов.
  - **Muxpress Rollback Guard:** Временные файлы перекодирования (`.temp.mkv`) заменяют оригинал только атомарно (`os.replace`) и только если сжатый файл оказался строго меньше исходного. При сбое или росте размера временный файл уничтожается, а оригинал остаётся нетронутым.
  - **Изоляция в RAM-диске (`/tmp`):** Вся рабочая директория агента вынесена в `tmpfs` (RAM-диск 4 ГБ). Агент физически не засоряет хранилище `/storage` временными скриптами.
* **Строгая неизменяемость раннера (Read-Only):** Код самого оператора, утилиты и регламенты (`recipes/`) монтируются строго в режиме `:ro`. Агент не может переписать собственные инструкции (`INSTRUCTIONS.md`) или логику раннера.
* **Downstream от `antigravity-sbx-patched`:** Образ оператора строится напрямую поверх `ghcr.io/retr0xcc/antigravity-sbx-patched:latest` с предварительно интегрированным и валидированным QNIX eligibility-патчем, залоченным бинарником `agy` и отключенными фоновыми автообновлениями.
* **Поддержка Docker Sandboxes (`sbx`) One-Shot:** Нативная поддержка запуска через `sbx run --rm` и декларативные шаблоны `sbxenv-media.yaml` для автономных задач без GPU.
* **Аппаратное ускорение AMD Radeon (AV1 & HEVC):** Нативная поддержка видеокарт AMD RDNA 3 (включая **Radeon RX 7700 XT**) через стек Mesa VA-API (`av1_vaapi`, `hevc_vaapi`). Аппаратное кодирование в **AV1** обеспечивает дополнительную экономию 20–30% дискового пространства по сравнению с HEVC при сохранении высокого качества.
* **Поддержка NVIDIA NVENC & Intel QuickSync / VA-API:** Автоматическое определение GPU хоста (`amd`, `nvidia`, `intel` или CPU fallback).
* **Встроенный движок Muxpress:** Интеграция проверенного конвейера для сопоставления серий, внешних дорожек озвучек (`.mka`), субтитров (`.ass`) и встраивания шрифтов (`-attach`) в единый монолитный контейнер `.mkv` для Jellyfin/Plex.
* **Обогащение метаданных (IMDb / Cyclopedia / Wikipedia):** Автоматическое семантическое распознавание канонических названий и годов релизов для фильмов, сериалов и аудиокниг.

---

## Архитектура и изоляция

> [!IMPORTANT]
> **Логика выбора рантайма (`--runtime auto`):**
> * **При задачах со сжатием на GPU (`--compress`, `media-compress`, `media-pipeline`):**
>   Автоматически используется стандартный **Docker Engine** (`--runtime docker`). Это необходимо, так как Docker позволяет прозрачно пробросить символьные устройства хоста (`--device=/dev/dri:/dev/dri` для AMD/Intel с группами `video`/`render` или `--gpus all` для NVIDIA) напрямую в контейнер без оверхеда виртуализации.
> * **При задачах без GPU (`media-link`, `media-remux` без сжатия):**
>   Автоматически используется **Docker Sandboxes (`sbx`)** (`--runtime sbx` при наличии CLI `sbx` на хосте). Это обеспечивает максимальную изоляцию в microVM, строгий сетевой allowlist, безопасную инъекцию `GEMINI_API_KEY` через proxy-managed credentials и работу в Zero-Copy режиме.
> * При необходимости вы можете принудительно переопределить рантайм флагами `--runtime docker` или `--runtime sbx`.

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                           Хост                              │
 │                                                             │
 │   Защищенные ресурсы хоста (Недоступны контейнеру):         │
 │   - Домашний каталог (~/.ssh, ~/.gnupg, ~/.aws, ~/.docker)  │
 │   - Корневая файловая система (/) и системные каталоги      │
 │   - Docker Socket (/var/run/docker.sock)                    │
 │                                                             │
 │   Физический раздел хранилища (ext4):                       │
 │   /home/retro/HDD-EXT4/ (единый корень Downloads и Media)   │
 │                                                             │
 │   Аппаратный ускоритель:                                    │
 │   - AMD Radeon (RX 7700 XT): /dev/dri/renderD128 (VA-API)   │
 │   - или NVIDIA GeForce/RTX: --gpus all (CUDA NVENC)         │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
    [Runtime: Docker Engine]          [Runtime: Docker Sandboxes]
    --device=/dev/dri:/dev/dri        sbx run --rm ./kits/media-operator
    (Прямой доступ к GPU)             (Строгая microVM изоляция)
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │               Песочница Antigravity Operator                │
 │               (База: antigravity-sbx-patched)               │
 │                                                             │
 │   - Непривилегированный пользователь: 'agent' (UID 1000)    │
 │   - Защита ядра: --security-opt=no-new-privileges:true      │
 │   - Быстрый RAM-диск: --tmpfs=/tmp:rw,nosuid,nodev,size=4g  │
 │   - Лимиты ресурсов: memory=8g, cpus=4, pids-limit=4096     │
 │   - Reaper зомби-процессов: --init (Tini PID 1)             │
 │   - Медиа-утилиты: ffmpeg (VAAPI/NVENC), mkvmerge, vainfo   │
 │   - Автономный агент: agy (QNIX patched, immutable)         │
 │   - Сессии: agy-operator-config ──► /home/agent/.gemini     │
 └───────────────────────────────┬─────────────────────────────┘
                                 │
                                 │  os.link(src, dst) внутри /storage
                                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                      Файловая система                       │
 │                                                             │
 │   /storage/Downloads/ ──[Hardlink (same inode)]──► /storage/│
 │   (Торрент раздаётся)                                Media/ │
 │                                                             │
 │   При AV1/HEVC сжатии:                                      │
 │   - Сжатый файл замещает только копию в Media/              │
 │   - Исходный инод в Downloads/ остаётся на раздаче!         │
 └─────────────────────────────────────────────────────────────┘
```

---

## Системные требования к хосту

* **Операционная система:** Linux (ядро 5.x/6.x) с поддержкой файловой системы ext4 / btrfs / zfs.
* **Контейнерный движок:** Docker Engine 20.10+ с Docker CLI и/или Docker Sandboxes (`sbx`).
* **Аппаратное ускорение (GPU):**
  * **AMD Radeon:** RX 7000 Series (RDNA 3 / Navi 3x, например Radeon RX 7700 XT) с аппаратным ускорением **AV1** (`av1_vaapi`) и **HEVC** (`hevc_vaapi`) через драйвер Mesa VA-API (`radeonsi`) на `/dev/dri/renderD128`.
  * **NVIDIA:** GeForce GTX 10xx, RTX 20xx/30xx/40xx с установленным драйвером NVIDIA и **NVIDIA Container Toolkit**.
  * **Intel:** Arc / Iris Xe с поддержкой QuickSync / VA-API.
* **Python:** Python 3.10+ на хосте для запуска CLI-диспетчера `bin/operate`.

> [!NOTE]
> Тестирование и профилирование проекта проводились на **AMD Radeon RX 7700 XT** (Linux, Mesa VA-API). Поддержка видеокарт NVIDIA и Intel заложена в архитектуру и покрыта тестами генерации команд, однако на физическом оборудовании NVIDIA/Intel код не проверялся ввиду отсутствия данных карт в наличии.

---

## Быстрый старт

### 1. Проверка готовности хост-системы

Выполните аудит окружения перед началом работы:

```bash
bin/operate doctor
```

Команда автоматически проверит:
* Наличие Docker Engine и Docker Sandboxes CLI (`sbx`).
* Аппаратный ускоритель GPU (AMD Radeon VA-API, NVIDIA CUDA NVENC, Intel).
* Наличие аппаратного энкодера **AV1** на видеокартах AMD RDNA 3 / Ada Lovelace.
* Наличие VA-API утилит (`vainfo`) и рецептов.

### 2. Сборка Docker-образа

Сборка происходит downstream от готового образа `antigravity-sbx-patched`:

```bash
bin/operate build
```

*(Опционально можно переопределить базовый образ через `--base-image <tag>`)*.

### 3. Просмотр доступных сценариев

```bash
bin/operate list
```

---

## Сценарии использования

| Рецепт | Назначение | Ресурсы | Время |
| :--- | :--- | :--- | :--- |
| **`media-link`** | Быстрая организация медиатеки через Zero-Copy Hardlinks (IMDb + Plex/Jellyfin naming) | 0% GPU, 0% CPU | ~5–10 сек |
| **`media-remux`** | Lossless сборка видео, дорожек озвучек, субтитров и шрифтов в единый MKV (`-c copy`) | Без пережатия | ~20–40 сек |
| **`media-compress`**| Аппаратное AV1 / HEVC 10-bit сжатие тяжелых релизов с защитой Rollback | GPU (AMD VA-API / NVENC) | Зависит от GPU |
| **`media-pipeline`**| Универсальный многоэтапный конвейер (Link + Remux + Compress) | Настраиваемый | Комплексный |

---

### Сценарий 1. Быстрый перенос из `Downloads` в `Media` (`media-link`)

Мгновенное добавление фильма или сериала в медиатеку с поиском на IMDb и сохранением торрент-раздачи (Zero-Copy):

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/The.Matrix.1999 /home/retro/HDD-EXT4/Media/Movies --imdb
```

### Сценарий 2. Сборка дорожек и шрифтов в единый MKV (`media-remux`)

Объединяет видео, дорожки озвучек (`.mka`), субтитры (`.ass`) и вложенные шрифты в монолитный файл для Jellyfin без перекодирования видеопотока:

```bash
bin/operate run media-remux /home/retro/HDD-EXT4/Downloads/Attack.on.Titan /home/retro/HDD-EXT4/Media/TV
```

### Сценарий 3. Аппаратное сжатие в AV1 на AMD Radeon RX 7700 XT (`media-compress`)

На видеокартах AMD RDNA 3 оператор автоматически выбирает аппаратный кодек **AV1** (`av1_vaapi`):

```bash
bin/operate run media-compress /home/retro/HDD-EXT4/Media/TV/Frieren --codec av1 --quality 28
```

* **Защита Rollback:** Если сжатый файл оказался больше исходного, временный файл удаляется и оригинал сохраняется.
* **Принудительное сжатие (`--force`):** Перекодирование даже файлов, которые уже сжаты, если их исходный битрейт избыточен (тяжёлые BDRip).

### Сценарий 4. Запуск через Docker Sandboxes (`sbx`) One-Shot

Для запуска в изолированной песочнице Docker Sandboxes microVM:

```bash
bin/operate run media-link /home/retro/HDD-EXT4/Downloads/Series /home/retro/HDD-EXT4/Media/TV --runtime sbx
```

Или прямой вызов через `sbx run`:

```bash
sbx run --rm ./kits/media-operator /home/retro/HDD-EXT4 -- \
  --dangerously-skip-permissions \
  --effort low \
  --output-format stream-json \
  -p "Организуй медиатеку в папке /storage/Media по правилам media-link"
```

---

## Справочник параметров CLI `bin/operate`

```text
operate run <recipe> <source> [destination] [опции]
```

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `recipe` | — | Имя рецепта (`media-pipeline`, `media-link`, `media-remux`, `media-compress`) |
| `source` | — | Путь к исходной папке в `Downloads` или `Media` |
| `destination` / `-d` | Автовыбор | Целевая папка медиатеки (`TV`, `Movies`, `Books`) |
| `--runtime` | `auto` | Движок изоляции: `auto` (выбирает лучший), `docker` (прямой GPU), `sbx` (микро-ВМ) |
| `--codec` | `auto` | Целевой видеокодек: `auto` (AV1 для RDNA 3/Ada, HEVC для старых), `av1`, `hevc`, `h264` |
| `--backend` | `auto` | Бэкенд энкодера: `auto` (AMD/Intel `vaapi`, NVIDIA `nvenc`, CPU `software`) |
| `--device` | Автовыбор | Путь к DRI render-ноде (например `/dev/dri/renderD128`) |
| `-q`, `--quality`, `--qp` | `28` | Параметр качества (CQP global_quality для VA-API, QP для NVENC, CRF для CPU) |
| `--preset` | `p6` | Пресет скорости/качества кодирования |
| `--mode` | `link` | Режим работы: `link`, `remux`, `compress`, `full` |
| `--remux` | `false` | Упаковать внешние дорожки/сабы/шрифты в единый `.mkv` |
| `--compress` | `false` | Включить аппаратное сжатие GPU |
| `--force`, `--force-reencode` | `false` | Принудительно сжать даже если видео уже в целевом кодеке |
| `--max-bitrate` | — | Порог битрейта в kbps (например `4500`): сжимать файлы, превышающие данный порог |
| `--imdb`, `--metadata`| `false` | Разрешить сеть и запросить метаданные (IMDb/Wiki/Cyclopedia) |
| `--dry-run` | `false` | Симуляция: вывод плана и команд без изменения диска |
| `--auto` | `false` | Запуск в автономном режиме без запроса подтверждений |

---

## Лицензия и отказ от ответственности

* Исходный код этого проекта распространяется под лицензией **[MIT](LICENSE)** (© 2026 Retr0xCC).
* **Disclaimer**: это независимый проект сообщества. Он не связан, не спонсируется и не одобрен компаниями Google LLC или Docker, Inc. «Google Antigravity» является товарным знаком Google LLC. «Docker» и «Docker Sandboxes» являются товарными знаками Docker, Inc.
