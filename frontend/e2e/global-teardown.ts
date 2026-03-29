import { stopMockApiServer } from "./mock-api-server";

export default async function globalTeardown(): Promise<void> {
  await stopMockApiServer();
  console.log("[E2E] Mock API server stopped");
}
