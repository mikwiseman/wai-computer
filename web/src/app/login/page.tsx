import { Suspense } from "react";
import { LoginClient, resolveLoginRedirect } from "./LoginClient";

export { resolveLoginRedirect };

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginClient />
    </Suspense>
  );
}
