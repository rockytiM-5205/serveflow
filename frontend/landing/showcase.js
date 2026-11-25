import { mountHeroDemo, mountScreenDemo } from "./demo.js";

const hero = document.getElementById("hero-demo");
const screen = document.getElementById("screen-demo");
if (hero) mountHeroDemo(hero, document.getElementById("hero-caption"));
if (screen) mountScreenDemo(screen, document.getElementById("screen-caption"));
