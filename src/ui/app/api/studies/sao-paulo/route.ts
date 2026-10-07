import { proxy } from "@/app/lib/brain";
export const runtime = "nodejs";
export function POST(request: Request) {
  return proxy("/studies/sao-paulo", request);
}
