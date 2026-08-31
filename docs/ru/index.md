---
layout: home

hero:
  name: Arachne
  text: Пульт управления сборками и инфраструктурой
  tagline: Один портал для сценариев, Forgejo Actions, Ansible, OpenTofu, временных стендов, живых логов и артефактов.
  actions:
    - theme: brand
      text: Начать работу
      link: /ru/getting-started/overview
    - theme: alt
      text: Справочник сценариев
      link: /ru/reference/scenario-syntax
    - theme: alt
      text: Golden Images
      link: /ru/operations/golden-images

features:
  - title: Запуск из одной формы
    details: Выберите сценарий, заполните параметры и запустите. Логи, состояние шагов, артефакты и инфраструктурные результаты остаются рядом с run.
  - title: Временные стенды как ресурс
    details: Arachne создаёт VM из Golden Images, хранит IP и VM metadata, поддерживает TTL и автоматически удаляет просроченные машины.
  - title: Инфраструктура без протекания кишок
    details: Сценарий описывает намерение. Spider сам получает node, storage и конфигурацию template из Proxmox API.
  - title: Процесс описан явно
    details: Параметры, шаги, триггеры и правила доступа лежат в версионируемом описании сценария.
  - title: Исполнители сменные
    details: Forgejo, Ansible и OpenTofu подключены через пауков. Ядро задаёт порядок, внешние системы выполняют работу.
---

Документация описывает текущее состояние Arachne с PostgreSQL lifecycle для временных машин, Golden Image profiles и live discovery Proxmox templates.

Для инфраструктурного provisioning начинайте с [Golden Images](/ru/operations/golden-images), затем переходите к [Proxmox и OpenTofu](/ru/operations/proxmox-opentofu).

Если старый пример расходится с русским справочником или исходниками, ориентируйтесь на актуальный русский справочник и код. Callback-примеры для Forgejo оставлены только для совместимости.
