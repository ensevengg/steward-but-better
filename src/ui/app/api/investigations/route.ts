import { proxy } from "@/app/lib/brain";
export const runtime = "nodejs";
export function GET(request: Request) {
  return proxy(`/state${new URL(request.url).search}`);
}
export function POST(request: Request) {
  return proxy("/cases", request);
}
