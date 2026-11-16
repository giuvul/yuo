import { I18nProvider } from "@lingui/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { i18n } from "./i18n";
import { OutboxProvider } from "./outbox/context";
import type { Outbox } from "./outbox/outbox";
import type { createAppRouter } from "./router";
import { TutorProvider } from "./tutor/context";

type Props = {
  router: ReturnType<typeof createAppRouter>;
  queryClient: QueryClient;
  outbox: Outbox;
};

export function App({ router, queryClient, outbox }: Props) {
  return (
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <OutboxProvider outbox={outbox}>
          <TutorProvider>
            <RouterProvider router={router} />
          </TutorProvider>
        </OutboxProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
}
