import { defineConfig } from "vitepress";

export default defineConfig({
  title: "Arachne",
  base: process.env.DOCS_BASE || "/",
  description: "Documentation for the Arachne CI/CD orchestration portal",
  cleanUrls: true,
  lastUpdated: process.env.DOCS_LAST_UPDATED !== "false",
  themeConfig: {
    nav: [
      { text: "Guide", link: "/getting-started/overview" },
      { text: "Reference", link: "/reference/scenario-syntax" },
      { text: "Architecture", link: "/architecture/overview" },
      { text: "Operations", link: "/operations/deployment" }
    ],
    search: { provider: "local" },
    sidebar: [
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
    ],
    socialLinks: [
      { icon: "github", link: "https://github.com/Aetton/arachne" }
    ],
    footer: {
      message: "Released under the Apache 2.0 License."
    }
  }
});
