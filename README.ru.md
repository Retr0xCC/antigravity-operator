[English](README.en.md) | **Русский**

# Antigravity Operator

> Тонкий хостовый лаунчер и исполнитель планов медиатеки Plex/Jellyfin ([TRaSH Guides](https://trash-guides.info/Hardlinks/Hardlinks-and-Instant-Moves/)), работающий в связке с изолированным Docker Sandbox (SBX) Mixin Kit.

[![CLI: operate](https://img.shields.io/badge/CLI-operate-blue.svg)](bin/operate)
[![Base: antigravity-sbx-patched](https://img.shields.io/badge/Base-antigravity--sbx--patched-blueviolet.svg)](https://github.com/Retr0xCC/antigravity-sbx-patched)
[![Runtime: Docker Sandboxes (SBX)](https://img.shields.io/badge/Runtime-Docker%20Sandboxes%20(SBX)-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/)
[![GPU: AMD AV1 & NVIDIA NVENC](https://img.shields.io/badge/GPU-AMD%20AV1%20%7C%20NVENC-ED1C24?logo=amd&logoColor=white)](#аппаратное-ускорение-gpu)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Новая архитектура: RO-песочница → План → Нативное исполнение на хосте

Старая модель прямого запуска тяжёлого Docker-контейнера с GPU-пробросом, root-правами и перезаписью файлов на хосте заменена на чистую двухфазную архитектуру:

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 1. ФАЗА АНАЛИЗА (Docker Sandbox microVM / SBX Kit)                     │
 │    - Исходные файлы торрентов монтируются строго в READ-ONLY (:ro)    │
 │    - Агент (agy) анализирует кодеки через ffprobe и mkvmerge           │
 │    - Сеть ограничена строгим allowlist (TMDb, IMDb, Wikipedia, Books) │
 │    - Вывод в отдельную RW-папку: plan.json, summary.md, apply.sh       │
 └───────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ 2. ФАЗА ПРИМЕНЕНИЯ (Нативно на хосте под правами пользователя)         │
 │    - Человек видит понятный отчет summary.md перед запуском            │
 │    - Хостовый раннер безопасно выполняет plan.json (shell=False)       │
 │    - Жесткие ссылки (os.link) для TRaSH Guides без дублирования места  │
 │    - Нативное GPU-кодирование (AMD VA-API AV1/HEVC, NVIDIA NVENC)      │
 │    - Торренты продолжают непрерывно раздаваться                        │
 └────────────────────────────────────────────────────────────────────────┘
```

### Преимущества новой архитектуры:
1. **100% безопасность исходных файлов:** Медиа-каталог примонтирован в `:ro`. Агент физически не способен удалить, испортить или переместить ни одного скачанного файла.
2. **Никаких проблем с UID/GID и OAuth-томами:** Вся сессия агента и токены изолированы внутри SBX, а применение плана происходит от вашего реального пользователя на хосте.
3. **Нативный GPU хоста:** Кодирование видео (AV1/HEVC) запускается локально без виртуализации, эмуляции драйверов и возни с `/dev/dri` внутри контейнера.
4. **Защита от шелл-инъекций:** План выполняется напрямую через системные вызовы Python (`os.link`, `os.makedirs`, `subprocess.run(shell=False)`). Спецсимволы в именах релизов (`$()`, кавычки, амперсанды) безопасны.

---

## Быстрый старт

### 1. Проверка готовности системы
```bash
bin/operate doctor
```
Проверит наличие Docker / SBX, хостовых мультимедиа-инструментов (`ffmpeg`, `mkvmerge`) и аппаратного видеоускорения GPU.

### 2. Полный цикл (Планирование + Интерактивное подтверждение)
```bash
bin/operate run /mnt/storage/Downloads/Torrents/Sousou_no_Frieren --dest /mnt/storage/Media/TV
```
1. Запустит песочницу в `:ro`.
2. Выведет в терминал красивую таблицу из `out/summary.md`.
3. Спросит: `Do you want to apply this plan on the host now? [y/N]`.
4. При подтверждении создаст структуру каталогов и жесткие ссылки `os.link`.

### 3. Раздельные шаги (Только план или Только применение)
```bash
# 1. Сгенерировать план без применения
bin/operate plan /mnt/storage/Downloads/Torrents/Sousou_no_Frieren --dest /mnt/storage/Media/TV --out ./out

# 2. Изучить сгенерированный отчет
cat ./out/summary.md

# 3. Применить готовый план на хосте
bin/operate apply ./out/plan.json
```

---

## Режимы работы (`--mode`)

| Режим | Действие | Перекодирование? | Исходные файлы | Результат |
| :--- | :--- | :--- | :--- | :--- |
| **`link`** *(по умолчанию)* | Жесткие ссылки (`os.link`) | Нет (0 CPU) | Не тронуты | Раздельные файлы видео, дорожек и субтитров |
| **`remux`** | Объединение видео + внешних дорожек и шрифтов в `.mkv` | Нет (`-c copy`) | Не тронуты | Единый монолитный `.mkv` на серию |
| **`compress`** | Аппаратное сжатие в AV1/HEVC | Да (GPU хоста) | Не тронуты | Сжатый файл (откат, если размер вырос) |
| **`full`** | Ремукс всех дорожек **И** аппаратное сжатие | Да (GPU хоста) | Не тронуты | Единый сжатый `.mkv` файл |

---

## Аппаратное ускорение GPU

Хостовый лаунчер автоматически опрашивает хост перед запуском планирования:
* **AMD Radeon (RX 7000 / RDNA 3):** аппаратный энкодер `av1_vaapi` или `hevc_vaapi`.
* **NVIDIA GeForce (RTX 40+ / Ampere / Turing):** аппаратный энкодер `av1_nvenc` или `hevc_nvenc`.
* **Intel Arc / UHD:** аппаратный энкодер `av1_vaapi` или `hevc_vaapi`.
* **CPU fallback:** программный энкодер `libx265`.

---

## Структура проекта

```text
antigravity-operator/
├── bin/
│   └── operate                # Единый CLI-интерфейс
├── core/
│   ├── cli.py                 # Диспетчер команд CLI
│   ├── gpu.py                 # Полноценный хостовый детектор GPU
│   ├── launcher.py            # Подготовка host_profile.json и запуск SBX
│   └── plan.py                # Безопасный хостовый раннер plan.json
├── kits/
│   └── media-operator/        # Mixin Kit для antigravity-sbx-patched
│       ├── spec.yaml          # Декларация кита и сетевой allowlist
│       ├── AGENTS.md          # Инструкции агенту (SOP Jellyfin/Plex)
│       └── Dockerfile         # Предварительно запеченные ffmpeg/mkvtoolnix
├── recipes/                   # Оригинальные рецепты и SOP
└── tests/
    └── test_compatibility.py  # Набор тестов совместимости и безопасности
```
