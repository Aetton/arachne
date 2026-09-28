# Необязательные спайдеры гипервизоров

Арахна поддерживает два независимых Brood-спайдера:

- `tofu-proxmox` — Proxmox VE;
- `tofu-ovirt` — oVirt Engine.

Общий runtime отвечает за процессы OpenTofu, отмену, изоляцию state, блокировку
параллельных операций одного стенда и сохранение параметров для destroy.
Адаптеры отдельно реализуют подключение, обнаружение template и создание VM.
Оба возвращают стандартный Brood Target: следующий Command-шаг не зависит от платформы.

## Установка

Пакеты выбираются **при сборке образа**. Чистая установка по умолчанию не включает
OpenTofu, Ansible, pywinrm и исполняемые модули спайдеров этих платформ.
Forgejo, GitLab и оркестрация сценариев остаются в ядре.

В `.env`:

```dotenv
# Только oVirt:
ARACHNE_PLUGINS=tofu-ovirt

# Или обе платформы и Ansible для установки ПО:
# ARACHNE_PLUGINS=tofu-proxmox,tofu-ovirt,ansible-local
```

Используйте обновлённый `docker-compose.yml.example`: блок build передаёт
`ARACHNE_PLUGINS` как build argument. Для существующего локального compose:

```yaml
services:
  arachne:
    build:
      context: .
      args:
        ARACHNE_PLUGINS: "${ARACHNE_PLUGINS:-}"
```

Затем:

```bash
docker compose up -d --build
```

Один бинарник tofu используется обоими спайдерами. Каждый модуль скачивает только
свой закреплённый провайдер при `tofu init`. Выбор спайдера не устанавливает второй
провайдер. Добавление пакета требует пересборки образа; одной смены runtime-env
недостаточно. Неизвестные пакеты и включение отсутствующего пакета отклоняются.

При запуске из исходников установите `api/requirements.txt`, задайте
`ARACHNE_PLUGINS` и установите OpenTofu в PATH для tofu-пакетов. Для `ansible-local`
дополнительно установите Ansible, openssh-client, sshpass и
`api/requirements-ansible.txt`. Это выбираемые build-bundles в одном репозитории,
не отдельные дистрибутивы PyPI и не установка через UI.

## Обновление существующей установки

Перед пересборкой прежней установки Proxmox + Ansible задайте:

```dotenv
ARACHNE_PLUGINS=tofu-proxmox,ansible-local
```

Для добавления oVirt допишите `,tofu-ovirt`. Проверьте build args в локальном compose.
Старые Proxmox profiles без connection и state `TOFU_STATE_ROOT/<name>` сохраняют
прежнее поведение и используют прежний endpoint/привязку токена. Нельзя менять
legacy endpoint, пока существуют старые стенды: сначала уничтожьте их на исходной
площадке. Новый профиль именованного подключения использует отдельное пространство state.

## Подключения и Golden Images

1. В **Control → Secrets** создайте credential: `token` для Proxmox или `basic`
   (username с realm и password) для oVirt.
2. В **Control → Гипервизоры** добавьте именованное подключение:
   `pve-lab`, `ovirt-test`, `ovirt-dev`.
3. Укажите endpoint: `https://pve.example.internal:8006/` либо
   `https://engine.example.internal/ovirt-engine/api`.
4. В **Golden Images** выберите подключение, живой template и credential для
   доступа к гостевой ОС. Это отдельный credential, не учётка Engine.

Платформа и endpoint существующего именованного подключения неизменяемы — для другой
площадки создайте новый ключ. Credential можно ротировать. Отключение подключения
запрещает новые VM, но сохраняет возможность destroy и TTL cleanup.
Доверенные CA монтируются существующим способом через `certs/`.

Профиль image однозначно привязан к подключению. Одинаковые template IDs на разных
площадках не смешиваются. Чтобы выбирать площадку при запуске, создайте профили,
например `redos8-pve` и `redos8-ovirt`, и задайте параметры сценария `image` и
`connection` (поле connection можно опустить при создании — оно берётся из image).
Несоответствие явно переданного connection профилю отклоняется до запуска tofu.

```yaml
- id: stand
  spider: tofu-ovirt
  action: brood
  with:
    name: test-${params.name}
    connection: ovirt-test
    image: redos8-ovirt
    lifetime: 2h
    resources:
      cpu: 4
      memory_gb: 8
    ip_cidr: 10.81.0.0/16
    # Если у гостя несколько интерфейсов:
    # ip_interface: eth0

- id: deploy
  spider: ansible-local
  action: command
  with:
    target: "${stand.artifact}"
    playbook: install-redvrm.yml
```

oVirt использует полный clone (`clone=true`) в кластере исходного template.
Сеть/vNIC profiles и диски наследуются от подготовленного template. Шаблон должен
быть пригоден для клонирования и иметь настроенную сеть и guest agent.
`resources` у oVirt поддерживает `cpu` и `memory_gb`; изменение размера диска пока
не поддерживается и явно отклоняется. Перенос в другой кластер/storage и создание
сети с нуля не входят в этот адаптер.

После apply адрес читается из `reporteddevices` Engine. Spider ждёт именно IPv4,
при необходимости фильтруя интерфейс и CIDR. При нескольких совпадениях возвращает
понятную ошибку, а не выбирает случайный IP. Ожидание адреса отменяемое и без общего
дедлайна Арахны; сетевые ошибки завершают шаг. Наличие IP не означает готовность
SSH/WinRM или завершение cloud-init — это проверяет следующий Command-шаг.
Внутренние ограничения ожидания API у провайдера OpenTofu остаются его собственными.

## State и удаление

Новые state размещаются в:

```text
TOFU_STATE_ROOT/<spider>/<connection>/<stand>/
```

Имя стенда может повторяться на разных подключениях. Одновременные операции над
одним state блокируются файловой блокировкой (Linux, общий persistent state volume).
Повторный provision поверх существующего state запрещён; сначала выполните destroy.

```yaml
- id: cleanup
  spider: tofu-ovirt
  action: destroy
  with:
    name: test-example
    connection: ovirt-test
```

Для destroy используется **сохранённый модуль и сохранённые входные параметры**;
живой template не требуется. Смена или удаление golden image не меняет площадку
удаления уже созданной VM. TTL вызывает исходный spider с исходным connection.
Пароли и токены не пишутся в manifest и не передаются в аргументах команд:
spider создаёт отдельное окружение дочернего процесса.

При ошибке или отмене apply созданная VM по возможности извлекается из локального
state и возвращается как artifact для последующей очистки. Это не транзакционный
rollback: при аварийном завершении процесса Арахны посреди apply проверьте state
и выполняйте destroy с исходными name/connection. Сохраняйте volume state и БД.

## Проверка перед эксплуатацией

Локальные тесты проверяют маршрутизацию TTL, раздельные credentials и state,
одинаковые VM IDs на разных площадках, ошибку apply и выбор IPv4 без настоящего
гипервизора. Перед рабочим запуском выполните создание, получение IP, передачу
artifact в Ansible и destroy одной тестовой VM на каждом используемом Engine.
