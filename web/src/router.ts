import { createRouter, createWebHistory } from "vue-router";

import ChatView from "./views/ChatView.vue";
import HelpView from "./views/HelpView.vue";
import NotFoundView from "./views/NotFoundView.vue";
import OperationsView from "./views/OperationsView.vue";
import SettingsView from "./views/SettingsView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "chat",
      component: ChatView,
    },
    {
      path: "/operations",
      name: "operations",
      component: OperationsView,
    },
    {
      path: "/settings",
      name: "settings",
      component: SettingsView,
    },
    {
      path: "/help",
      name: "help",
      component: HelpView,
    },
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: NotFoundView,
    },
  ],
});

export default router;
