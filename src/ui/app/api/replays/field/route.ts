import { proxy } from "@/app/lib/brain";
export const runtime = "nodejs";
export function POST(request: Request) {
  return proxy("/replays/field", request);
}
