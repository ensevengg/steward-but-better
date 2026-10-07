import { proxy } from "@/app/lib/brain";
export const runtime = "nodejs";
type Context = { params: Promise<{ id: string }> };
export async function GET(_: Request, context: Context) {
  return proxy(`/cases/${encodeURIComponent((await context.params).id)}`);
}
export async function PATCH(request: Request, context: Context) {
  return proxy(
    `/cases/${encodeURIComponent((await context.params).id)}`,
    request,
  );
}
