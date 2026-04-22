import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "deck",
      component: () => import("./views/Deck.vue"),
    },
    {
      path: "/me",
      name: "me",
      component: () => import("./views/Me.vue"),
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/",
    },
  ],
});
