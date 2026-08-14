#include "OSMCityGeometry.h"

#include "Algo/Reverse.h"
#include "GeometryScript/MeshNormalsFunctions.h"
#include "GeometryScript/MeshPrimitiveFunctions.h"
#include "UDynamicMesh.h"

namespace
{
	FGeometryScriptPrimitiveOptions DefaultPrimitiveOptions()
	{
		FGeometryScriptPrimitiveOptions Options;
		Options.PolygroupMode = EGeometryScriptPrimitivePolygroupMode::PerFace;
		return Options;
	}

	/** Signed area of a ring; > 0 means CCW in the (X, Y) plane. */
	double SignedArea(const TArray<FVector2D>& Ring)
	{
		double Sum = 0.0;
		const int32 N = Ring.Num();
		for (int32 i = 0; i < N; ++i)
		{
			const FVector2D& A = Ring[i];
			const FVector2D& B = Ring[(i + 1) % N];
			Sum += A.X * B.Y - B.X * A.Y;
		}
		return 0.5 * Sum;
	}

	void AppendQuad(UDynamicMesh* TargetMesh, const FGeometryScriptPrimitiveOptions& Options,
		const FVector2D& HalfExtents, const FTransform& Placement)
	{
		const TArray<FVector2D> Quad = {
			FVector2D(-HalfExtents.X, -HalfExtents.Y),
			FVector2D(HalfExtents.X, -HalfExtents.Y),
			FVector2D(HalfExtents.X, HalfExtents.Y),
			FVector2D(-HalfExtents.X, HalfExtents.Y),
		};
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendTriangulatedPolygon(
			TargetMesh, Options, Placement, Quad, /*bAllowSelfIntersections=*/false);
	}
}

int32 UOSMCityGeometry::AppendBuildings(UDynamicMesh* TargetMesh, const FOSMCity& City,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh)
	{
		return 0;
	}
	const FGeometryScriptPrimitiveOptions PrimitiveOptions = DefaultPrimitiveOptions();
	int32 Built = 0;

	for (const FOSMBuilding& B : City.Buildings)
	{
		if (B.OutlineCm.Num() < 3)
		{
			continue;
		}
		if (Options.MinFootprintAreaCm2 > 0.f &&
			B.BoxLengthCm * B.BoxWidthCm < Options.MinFootprintAreaCm2)
		{
			continue;
		}

		// Extrude in the footprint's own frame: vertices relative to the centroid,
		// transform carries the world placement. Keeps the maths in small numbers.
		TArray<FVector2D> Local;
		Local.Reserve(B.OutlineCm.Num());
		for (const FVector2D& P : B.OutlineCm)
		{
			Local.Add(P - B.CentroidCm);
		}
		// AppendSimpleExtrudePolygon needs CCW input or the solid comes out inside-out.
		if (SignedArea(Local) < 0.0)
		{
			Algo::Reverse(Local);
		}

		const FTransform Placement(
			FRotator::ZeroRotator,
			FVector(B.CentroidCm.X, B.CentroidCm.Y, B.BaseCm));

		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSimpleExtrudePolygon(
			TargetMesh, PrimitiveOptions, Placement, Local,
			FMath::Max(50.f, B.HeightCm + Options.HeightBiasCm),
			/*HeightSteps=*/0, /*bCapped=*/true,
			EGeometryScriptPrimitiveOriginMode::Base);
		++Built;
	}

	UGeometryScriptLibrary_MeshNormalsFunctions::RecomputeNormals(
		TargetMesh, FGeometryScriptCalculateNormalsOptions());
	return Built;
}

int32 UOSMCityGeometry::AppendRoads(UDynamicMesh* TargetMesh, const FOSMCity& City,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh)
	{
		return 0;
	}
	const FGeometryScriptPrimitiveOptions PrimitiveOptions = DefaultPrimitiveOptions();
	int32 Built = 0;

	for (const FOSMRoad& R : City.Roads)
	{
		const float HalfWidth = FMath::Max(100.f, R.WidthCm * 0.5f);
		// Bridges/tunnels get separated vertically so they do not fight the surface.
		const float Z = Options.RoadZOffsetCm + R.Layer * 400.f;

		for (int32 i = 0; i + 1 < R.PointsCm.Num(); ++i)
		{
			const FVector2D A = R.PointsCm[i];
			const FVector2D B = R.PointsCm[i + 1];
			const FVector2D Delta = B - A;
			const float Length = Delta.Size();
			if (Length < 1.f)
			{
				continue;
			}

			const FVector2D Mid = (A + B) * 0.5f;
			const float YawDeg = FMath::RadiansToDegrees(FMath::Atan2(Delta.Y, Delta.X));
			AppendQuad(TargetMesh, PrimitiveOptions,
				FVector2D(Length * 0.5f, HalfWidth),
				FTransform(FRotator(0.f, YawDeg, 0.f), FVector(Mid.X, Mid.Y, Z)));
		}

		// Square patch at each interior vertex, so corners have no wedge-shaped gap.
		for (int32 i = 1; i + 1 < R.PointsCm.Num(); ++i)
		{
			AppendQuad(TargetMesh, PrimitiveOptions,
				FVector2D(HalfWidth, HalfWidth),
				FTransform(FRotator::ZeroRotator,
					FVector(R.PointsCm[i].X, R.PointsCm[i].Y, Z)));
		}
		++Built;
	}

	return Built;
}

bool UOSMCityGeometry::AppendGround(UDynamicMesh* TargetMesh, const FOSMCity& City,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh || !City.BoundsCm.bIsValid)
	{
		return false;
	}
	const FVector2D Padding(Options.GroundPaddingCm * 2.f, Options.GroundPaddingCm * 2.f);
	const FVector2D Size = City.BoundsCm.GetSize() + Padding;
	const FVector2D Centre = City.BoundsCm.GetCenter();

	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendBox(
		TargetMesh, DefaultPrimitiveOptions(),
		FTransform(FRotator::ZeroRotator, FVector(Centre.X, Centre.Y, -100.f)),
		Size.X, Size.Y, /*DimensionZ=*/100.f);
	return true;
}
