import { createBrowserRouter, redirect, type LoaderFunctionArgs } from "react-router";
import { supabase } from "@/integrations/supabase/client";
import { RootLayout, NotFoundComponent, ErrorComponent } from "@/pages/RootLayout";
import { Landing } from "@/pages/Landing";
import { AuthPage } from "@/pages/Auth";
import { Dashboard } from "@/pages/Dashboard";

/** Guard for authenticated routes: redirect to /sign-in when there is no user. */
async function requireUser() {
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw redirect("/sign-in");
  return { user: data.user };
}

/** Legacy /auth?mode=signin|signup links → dedicated routes. */
function legacyAuthRedirect({ request }: LoaderFunctionArgs) {
  const mode = new URL(request.url).searchParams.get("mode");
  return redirect(mode === "signup" ? "/sign-up" : "/sign-in");
}

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    errorElement: <ErrorComponent />,
    children: [
      { path: "/", element: <Landing /> },
      { path: "/sign-in", element: <AuthPage mode="signin" /> },
      { path: "/sign-up", element: <AuthPage mode="signup" /> },
      { path: "/auth", loader: legacyAuthRedirect },
      { id: "authenticated", path: "/app", loader: requireUser, element: <Dashboard /> },
      { path: "*", element: <NotFoundComponent /> },
    ],
  },
]);
