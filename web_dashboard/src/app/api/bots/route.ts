import { NextResponse } from "next/server";
import { loadAllBots, loadBot } from "../../../lib/loadBots";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  if (id) {
    const bot = loadBot(id);
    if (!bot) {
      return NextResponse.json({ ok: false, message: "Unknown bot" }, { status: 404 });
    }
    return NextResponse.json({ ok: true, bot });
  }
  return NextResponse.json({ ok: true, ...loadAllBots() });
}
