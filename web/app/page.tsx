"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { LoadingState } from "@/components/ui/FeedbackStates";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-[#0B0F14] flex items-center justify-center">
        <LoadingState message="Redirecting to Control Tower..." />
      </div>
    </ProtectedRoute>
  );
}
