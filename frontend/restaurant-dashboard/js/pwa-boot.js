/* Every dashboard page: make it installable (and able to show order alerts) by registering the app's service worker. */
import { mountInstallBanner } from "../../shared/js/install-banner.js";
import { registerServiceWorker, watchInstall } from "../../shared/js/pwa.js";

watchInstall();
registerServiceWorker("sw.js", "./");
mountInstallBanner({ message: "Install ServeFlow on this device: open it in one tap and get an alert for every new order." });
