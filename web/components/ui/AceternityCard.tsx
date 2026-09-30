"use client";

import React, { useRef, useState } from "react";

export function PerspectiveCard({
  children,
  className = "",
  containerClassName = "",
}: {
  children: React.ReactNode;
  className?: string;
  containerClassName?: string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [rotateX, setRotateX] = useState(0);
  const [rotateY, setRotateY] = useState(0);
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Calculate rotation (-8deg to 8deg)
    const rY = ((mouseX - width / 2) / (width / 2)) * 6;
    const rX = -((mouseY - height / 2) / (height / 2)) * 6;

    setRotateX(rX);
    setRotateY(rY);
  };

  const handleMouseEnter = () => {
    setIsHovered(true);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setRotateX(0);
    setRotateY(0);
  };

  return (
    <div
      className={`perspective-1000 ${containerClassName}`}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        ref={cardRef}
        style={{
          transform: isHovered
            ? `rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateZ(10px)`
            : "rotateX(0deg) rotateY(0deg) translateZ(0px)",
          transition: isHovered ? "transform 0.05s ease-out" : "transform 0.4s ease-out",
        }}
        className={`transform-style-3d relative rounded-xl border border-arch bg-card transition-shadow ${
          isHovered ? "shadow-arch-lg border-arch-orange/40" : "shadow-arch-sm"
        } ${className}`}
      >
        {/* Subtle Ambient Light Reflection Glare */}
        {isHovered && (
          <div
            className="absolute inset-0 pointer-events-none rounded-xl opacity-30 z-10"
            style={{
              background: `radial-gradient(circle at ${50 + rotateY * 5}% ${
                50 - rotateX * 5
              }%, rgba(217, 94, 0, 0.25) 0%, transparent 60%)`,
            }}
          />
        )}
        {children}
      </div>
    </div>
  );
}
