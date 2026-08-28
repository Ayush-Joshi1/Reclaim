import { NextResponse } from "next/server";

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${backendUrl.replace(/\/$/, "")}/api/recovery/history`, {
      cache: "no-store",
    });
    const responseBody: unknown = await response.json().catch(() => ({ detail: "Backend returned an invalid response." }));
    return NextResponse.json(responseBody, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "The recovery backend could not be reached." },
      { status: 502 },
    );
  }
}

export async function POST(request: Request) {
  const workflowSecret = process.env.RECLAIM_WORKFLOW_SECRET;
  if (!workflowSecret) {
    return NextResponse.json(
      { detail: "Recovery workflow secret is not configured on the server." },
      { status: 503 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Request body must be valid JSON." }, { status: 400 });
  }

  try {
    const response = await fetch(`${backendUrl.replace(/\/$/, "")}/api/workflows/recovery`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Reclaim-Workflow-Secret": workflowSecret,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const responseBody: unknown = await response.json().catch(() => ({ detail: "Backend returned an invalid response." }));
    return NextResponse.json(responseBody, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "The recovery backend could not be reached." },
      { status: 502 },
    );
  }
}