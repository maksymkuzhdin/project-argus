import { startMockApiServer, MOCK_API_PORT } from "./mock-api-server";

export default async function globalSetup(): Promise<void> {
  await startMockApiServer();
  console.log(
    `[E2E] Mock API server started on http://localhost:${MOCK_API_PORT}`
  );
}
