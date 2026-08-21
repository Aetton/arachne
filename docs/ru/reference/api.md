# HTTP API

Arachne работает как HTML-портал. Интерактивная схема FastAPI доступна по `/docs`,
а ниже собраны маршруты приложения.

## Служебные и сессия

| Метод и путь | Доступ | Назначение |
|---|---|---|
| `GET /healthz` | публичный | проверка живости |
| `GET /static/...` | публичный | статика |
| `GET /wiki/...` | публичный | собранная документация |
| `GET /login` | публичный | форма входа |
| `POST /login` | публичный | создать сессию |
| `GET /logout` | публичный | удалить cookie |

Cookie `arachne_session` имеет `HttpOnly` и `SameSite=Lax`, но код пока не выставляет
`Secure`.

## Оператор

| Метод и путь | Назначение |
|---|---|
| `GET /` | dashboard |
| `GET /scenarios/{slug}/form` | форма сценария |
| `POST /scenarios/{slug}/run` | ручной запуск |
| `GET /runs/{id}/view` | карточка запуска |
| `POST /runs/{id}/cancel` | best-effort отмена |
| `GET /runs/history` | последние 15 запусков |
| `GET /runs/{id}/stream` | SSE логов |

Форма и запуск проверяют ACL. Просмотр конкретного run, SSE и cancel требуют входа,
но пока не проверяют владельца или ACL сценария.

## Callback совместимости

| Метод и путь | Тело |
|---|---|
| `POST /api/threads/{build_id}/signal` | `{step, status, output}` |
| `POST /api/threads/{build_id}/status` | `{status, artifacts}` |

Токен принимается в `X-Arachne-Token` или `?token=`. Маршруты остались от старого
hub-контракта; Forgejo spider v16 работает через Actions API.

## Администрирование

Все маршруты требуют роль `admin`.

| Маршруты | Назначение |
|---|---|
| `/admin/users...` | список, создание, изменение и удаление пользователей |
| `/admin/scenarios...` | список, редактор, сохранение и восстановление версий |
| `POST /admin/components` | создать или обновить компонент |
| `POST /admin/components/{slug}/delete` | удалить свободный компонент |
| `GET /admin/scenarios-export.yaml` | экспорт YAML |
| `/admin/rbac`, `POST /admin/roles`, `POST /admin/teams` | роли и команды |
| `GET /api/admin/scenario-dsl` | метаданные DSL для редактора |

Отдельного endpoint импорта нет: браузер разбирает YAML и последовательно вызывает
endpoints компонентов и сценариев.
