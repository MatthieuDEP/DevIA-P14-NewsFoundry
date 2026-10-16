import Image from "next/image";

export default function RobotIcon({ size = 22 }) {
  return (
    <Image
      src="/robot-icon.png"
      alt=""
      width={size}
      height={Math.round(size * 67 / 82)}
      aria-hidden="true"
      unoptimized
    />
  );
}
