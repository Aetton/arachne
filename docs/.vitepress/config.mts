import { defineConfig } from "vitepress";

const englishSidebar = [
  {
    text: "Getting started",
    items: [
      { text: "Overview", link: "/getting-started/overview" },
      { text: "Installation", link: "/getting-started/installation" },
      { text: "First scenario", link: "/getting-started/first-scenario" }
    ]
  },
  {
    text: "User guide",
    items: [
      { text: "Scenarios", link: "/user-guide/scenarios" },
      { text: "Components", link: "/user-guide/components" }
    ]
  },
  {
    text: "Reference",
    items: [
      { text: "Scenario syntax", link: "/reference/scenario-syntax" },
      { text: "Configuration", link: "/reference/configuration" }
    ]
  },
  {
    text: "Architecture",
    items: [{ text: "Overview", link: "/architecture/overview" }]
  },
  {
    text: "Development",
    items: [{ text: "Local setup", link: "/development/local-setup" }]
  },
  {
    text: "Operations",
    items: [
      { text: "Deployment", link: "/operations/deployment" },
      { text: "Troubleshooting", link: "/operations/troubleshooting" }
    ]
  },
  {
    text: "Decisions",
    items: [{ text: "Architecture decisions", link: "/decisions/" }]
  }
];

const russianSidebar = [
  {
    text: "Начало работы",
    items: [
      { text: "Обзор", link: "/ru/getting-started/overview" },
      { text: "Установка", link: "/ru/getting-started/installation" },
      { text: "Первый сценарий", link: "/ru/getting-started/first-scenario" }
    ]
  },
  {
    text: "Руководство пользователя",
    items: [
      { text: "Сценарии", link: "/ru/user-guide/scenarios" },
      { text: "Компоненты", link: "/ru/user-guide/components" }
    ]
  },
  {
    text: "Справочник",
    items: [
      { text: "Синтаксис сценариев", link: "/ru/reference/scenario-syntax" },
      { text: "Конфигурация", link: "/ru/reference/configuration" }
    ]
  },
  {
    text: "Архитектура",
    items: [{ text: "Обзор", link: "/ru/architecture/overview" }]
  },
  {
    text: "Разработка",
    items: [{ text: "Локальный запуск", link: "/ru/development/local-setup" }]
  },
  {
    text: "Эксплуатация",
    items: [
      { text: "Развёртывание", link: "/ru/operations/deployment" },
      { text: "Диагностика", link: "/ru/operations/troubleshooting" }
    ]
  },
  {
    text: "Решения",
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
        outline: { label: "На этой странице" },
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
