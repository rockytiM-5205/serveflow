/* ServeFlow for restaurants: the dashboard as an installable app, with order alerts. Scope: /restaurant-dashboard/ */
importScripts("/shared/js/sw-core.js");
serveflowServiceWorker({ name: "dashboard", push: true });
