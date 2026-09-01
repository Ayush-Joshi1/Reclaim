import { NextResponse } from "next/server";

function getBackendUrl(): string {
  const url = process.env.RECLAIM_BACKEND_URL;

  if (!url) {
    throw new Error("RECLAIM_BACKEND_URL is not configured");
  }

  return url.replace(/\/$/, "");
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);

  const paymentId = searchParams.get("payment_id");
  const limit = searchParams.get("limit");

  const query = new URLSearchParams();

  if (paymentId) {
    query.set("payment_id", paymentId);
  }

  if (limit) {
    query.set("limit", limit);
  }

  try {
    const backendUrl = getBackendUrl();

    const backendQuery = query.toString()
      ? `?${query.toString()}`
      : "";

    const response = await fetch(
      `${backendUrl}/api/recovery/history${backendQuery}`,
      {
        cache: "no-store",
      }
    );

    const responseBody: unknown = await response
      .json()
      .catch(() => ({
        detail: "Backend returned an invalid response.",
      }));

    return NextResponse.json(responseBody, {
      status: response.status,
    });
  } catch {
    return NextResponse.json(
      {
        detail: "The recovery backend could not be reached.",
      },
      {
        status: 502,
      }
    );
  }
}

export async function POST(request: Request) {
  const workflowSecret = process.env.RECLAIM_WORKFLOW_SECRET;

  if (!workflowSecret) {
    return NextResponse.json(
      {
        detail:
          "Recovery workflow secret is not configured on the server.",
      },
      {
        status: 503,
      }
    );
  }

  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        detail: "Request body must be valid JSON.",
      },
      {
        status: 400,
      }
    );
  }

  try {
    const backendUrl = getBackendUrl();

    const response = await fetch(
      `${backendUrl}/api/workflows/recovery`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Reclaim-Workflow-Secret": workflowSecret,
        },
        body: JSON.stringify(body),
        cache: "no-store",
      }
    );

    const responseBody: unknown = await response
      .json()
      .catch(() => ({
        detail: "Backend returned an invalid response.",
      }));

    return NextResponse.json(responseBody, {
      status: response.status,
    });
  } catch {
    return NextResponse.json(
      {
        detail: "The recovery backend could not be reached.",
      },
      {
        status: 502,
      }
    );
  }
}