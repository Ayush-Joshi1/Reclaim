import { NextResponse } from "next/server";

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${backendUrl.replace(/\/$/, "")}/api/recovery/summary`, {
      cache: "no-store",
    });
    const body: unknown = await response.json().catch(() => ({ detail: "Backend returned an invalid response." }));
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "The recovery backend could not be reached." }, { status: 502 });
  }
}