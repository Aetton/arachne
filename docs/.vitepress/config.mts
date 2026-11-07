import { defineConfig } from "vitepress";

const englishSidebar = [
  { text: "Documentation", link: "/", items: [{ text: "Contents", link: "/" }] },
  {
    text: "Getting started",
    collapsed: true,
    items: [
      { text: "Overview", link: "/getting-started/overview" },
      { text: "Installation", link: "/getting-started/installation" },
      { text: "First scenario", link: "/getting-started/first-scenario" }
    ]
  },
  {
    text: "User guide",
    collapsed: true,
    items: [
      { text: "Scenarios", link: "/user-guide/scenarios" },
      { text: "Components", link: "/user-guide/components" }
    ]
  },
  {
    text: "Reference",
    collapsed: true,
    items: [
      { text: "Scenario syntax", link: "/reference/scenario-syntax" },
      { text: "Configuration", link: "/reference/configuration" }
    ]
  },
  {
    text: "Architecture",
    collapsed: true,
    items: [{ text: "Overview", link: "/architecture/overview" }]
  },
  {
    text: "Development",
    collapsed: true,
    items: [{ text: "Local setup", link: "/development/local-setup" }]
  },
  {
    text: "Operations",
    collapsed: true,
    items: [
      { text: "Deployment", link: "/operations/deployment" },
      { text: "Troubleshooting", link: "/operations/troubleshooting" }
    ]
  },
  {
    text: "Decisions",
    collapsed: true,
    items: [{ text: "Architecture decisions", link: "/decisions/" }]
  }
];

const russianSidebar = [
  { text: "Документация", items: [{ text: "Содержание", link: "/ru/" }] },
  {
    text: "Начало работы",
    collapsed: true,
    items: [
      { text: "Обзор", link: "/ru/getting-started/overview" },
      { text: "Установка", link: "/ru/getting-started/installation" },
      { text: "Первый сценарий", link: "/ru/getting-started/first-scenario" }
    ]
  },
  {
    text: "Руководство пользователя",
    collapsed: true,
    items: [
      { text: "Работа оператора", link: "/ru/user-guide/operator" },
      { text: "Сценарии", link: "/ru/user-guide/scenarios" },
      { text: "Компоненты", link: "/ru/user-guide/components" },
      { text: "Администрирование", link: "/ru/user-guide/administration" },
      { text: "Роли и доступ", link: "/ru/user-guide/access" }
    ]
  },
  {
    text: "Справочник",
    collapsed: true,
    items: [
      { text: "Синтаксис сценариев", link: "/ru/reference/scenario-syntax" },
      { text: "Пауки", link: "/ru/reference/spiders" },
      { text: "Триггеры", link: "/ru/reference/triggers" },
      { text: "HTTP API", link: "/ru/reference/api" },
      { text: "Конфигурация", link: "/ru/reference/configuration" },
      { text: "Ограничения", link: "/ru/reference/limitations" }
    ]
  },
  {
    text: "Интеграции",
    collapsed: true,
    items: [{ text: "Forgejo Actions", link: "/ru/integrations/forgejo" }]
  },
  {
    text: "Архитектура",
    collapsed: true,
    items: [{ text: "Обзор", link: "/ru/architecture/overview" }]
  },
  {
    text: "Разработка",
    collapsed: true,
    items: [
      { text: "Локальный запуск", link: "/ru/development/local-setup" },
      { text: "Расширение Arachne", link: "/ru/development/extending" }
    ]
  },
  {
    text: "Эксплуатация",
    collapsed: true,
    items: [
      { text: "Развёртывание", link: "/ru/operations/deployment" },
      { text: "Golden Images", link: "/ru/operations/golden-images" },
      { text: "Пакеты спайдеров и подключения", link: "/ru/operations/optional-spiders" },
      { text: "Proxmox и OpenTofu", link: "/ru/operations/proxmox-opentofu" },
      { text: "Резервные копии и миграция", link: "/ru/operations/backup-and-migration" },
      { text: "Диагностика", link: "/ru/operations/troubleshooting" }
    ]
  },
  {
    text: "Решения",
    collapsed: true,
    items: [{ text: "Архитектурные решения", link: "/ru/decisions/" }]
  }
];

export default defineConfig({
  title: "Arachne",
  base: process.env.DOCS_BASE || "/",
  description: "Documentation for the Arachne CI/CD orchestration portal",
  cleanUrls: true,
  lastUpdated: process.env.DOCS_LAST_UPDATED !== "false",
  locales: {
    root: {
      label: "English",
      lang: "en-US"
    },
    ru: {
      label: "Русский",
      lang: "ru-RU",
      link: "/ru/",
      description: "Документация портала оркестрации CI/CD Arachne"
    }
  },
  themeConfig: {
    search: { provider: "local" },
    outline: { level: [2, 3] },
    socialLinks: [
      { icon: "github", link: "https://github.com/Aetton/arachne" }
    ],
    locales: {
      root: {
        nav: [
          { text: "Guide", link: "/getting-started/overview" },
          { text: "Reference", link: "/reference/scenario-syntax" },
          { text: "Architecture", link: "/architecture/overview" },
          { text: "Operations", link: "/operations/deployment" }
        ],
        sidebar: englishSidebar,
        outline: { level: [2, 3], label: "On this page" },
        footer: {
          message: "Released under the Apache 2.0 License."
        }
      },
      ru: {
        nav: [
          { text: "Руководство", link: "/ru/getting-started/overview" },
          { text: "Справочник", link: "/ru/reference/scenario-syntax" },
          { text: "Архитектура", link: "/ru/architecture/overview" },
          { text: "Эксплуатация", link: "/ru/operations/deployment" }
        ],
        sidebar: russianSidebar,
        outline: { level: [2, 3], label: "На этой странице" },
        docFooter: {
          prev: "Предыдущая страница",
          next: "Следующая страница"
        },
        lastUpdated: {
          text: "Обновлено"
        },
        darkModeSwitchLabel: "Оформление",
        sidebarMenuLabel: "Меню",
        returnToTopLabel: "Наверх",
        langMenuLabel: "Выбрать язык",
        footer: {
          message: "Распространяется по лицензии Apache 2.0."
        }
      }
    }
  }
});
