/** The AEGIS AI mark. Height is fixed; width follows the artwork's natural aspect ratio (~1.27:1). */
export function BrandLogo({ height = 32, className }: { height?: number; className?: string }) {
  return (
    <img src="/brand/aegis-logo.png" alt="AEGIS AI logo" height={height} width={Math.round(height * 1.274)}
      className={className} style={{ height, width: "auto" }} draggable={false} />
  );
}
