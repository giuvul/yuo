import { createRouter, type RouterHistory } from "@tanstack/react-router";
import { rootRoute } from "./routes/root";
import { indexRoute } from "./routes/index";
import { pathsRoute } from "./routes/paths";
import { lessonRoute } from "./routes/lessonReader";
import { pathNewRoute } from "./routes/pathNew";
import { pathViewRoute } from "./routes/pathView";
import { practiceRoute } from "./routes/practice";
import { jobsRoute } from "./routes/jobs";
import { placementRoute } from "./routes/placement";
import { progressRoute } from "./routes/progress";
import { reviewChooserRoute, reviewHubRoute, reviewSessionRoute } from "./routes/review";
import { settingsRoute } from "./routes/settings";
import { setupRoute } from "./routes/setup";
import { signInRoute } from "./routes/signIn";
import { devicesRoute } from "./routes/devices";
import { skillTestRoute } from "./routes/skillTest";
import { mockExamRoute } from "./routes/mockExam";
import { nextStepsRoute } from "./routes/nextSteps";
import { tutorMemoryRoute } from "./routes/tutorMemory";
import { importRoute } from "./routes/importPage";
import { designRoute, designTreeRoute } from "./routes/design";

const routeTree = rootRoute.addChildren([
  indexRoute,
  pathsRoute,
  setupRoute,
  pathNewRoute,
  pathViewRoute,
  lessonRoute,
  practiceRoute,
  skillTestRoute,
  mockExamRoute,
  nextStepsRoute,
  placementRoute,
  progressRoute,
  reviewChooserRoute,
  reviewHubRoute,
  reviewSessionRoute,
  jobsRoute,
  settingsRoute,
  devicesRoute,
  signInRoute,
  tutorMemoryRoute,
  importRoute,
  designRoute,
  designTreeRoute,
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    defaultPreload: "intent",
    history,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
