#include "OSMCityGeometry.h"

#include "Algo/Reverse.h"
#include "GeometryScript/MeshNormalsFunctions.h"
#include "GeometryScript/MeshPrimitiveFunctions.h"
#include "UDynamicMesh.h"

DEFINE_LOG_CATEGORY_STATIC(LogOSMGeometry, Log, All);

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

int32 UOSMCityGeometry::AppendExtrudes(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh)
	{
		return 0;
	}
	const FGeometryScriptPrimitiveOptions PrimitiveOptions = DefaultPrimitiveOptions();
	int32 Built = 0;

	for (const FOSMExtrude& Node : Scene.Extrudes)
	{
		if (Node.Outline.Num() < 3)
		{
			continue;
		}
		if (Options.MinFootprintAreaCm2 > 0.f && Node.AreaCm2 < Options.MinFootprintAreaCm2)
		{
			continue;
		}

		// Sweep in the ring's own frame: vertices relative to the centroid, transform
		// carries the world placement. Keeps the maths in small numbers.
		TArray<FVector2D> Local;
		Local.Reserve(Node.Outline.Num());
		for (const FVector2D& P : Node.Outline)
		{
			Local.Add(P - Node.CentroidCm);
		}
		// AppendSimpleExtrudePolygon needs CCW input or the solid comes out inside-out.
		if (SignedArea(Local) < 0.0)
		{
			Algo::Reverse(Local);
		}

		const FTransform Placement(
			FRotator::ZeroRotator,
			FVector(Node.CentroidCm.X, Node.CentroidCm.Y, Node.BaseCm));

		// HeightCm is the absolute top and BaseCm the absolute bottom, both decided by
		// the pipeline; this only sweeps the difference.
		UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSimpleExtrudePolygon(
			TargetMesh, PrimitiveOptions, Placement, Local,
			FMath::Max(50.f, Node.HeightCm - Node.BaseCm + Options.HeightBiasCm),
			/*HeightSteps=*/0, /*bCapped=*/true,
			EGeometryScriptPrimitiveOriginMode::Base);
		++Built;
	}

	UGeometryScriptLibrary_MeshNormalsFunctions::RecomputeNormals(
		TargetMesh, FGeometryScriptCalculateNormalsOptions());
	return Built;
}

int32 UOSMCityGeometry::AppendMeshes(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh)
	{
		return 0;
	}
	const FGeometryScriptPrimitiveOptions PrimitiveOptions = DefaultPrimitiveOptions();
	int32 Triangles = 0;

	// Vertices are absolute world centimetres, so they append with an identity transform:
	// whatever the pipeline computed is exactly what gets built.
	for (const FOSMMesh& Node : Scene.Meshes)
	{
		for (int32 i = 0; i + 2 < Node.Indices.Num(); i += 3)
		{
			const TArray<FVector> Triangle = {
				Node.Vertices[Node.Indices[i]],
				Node.Vertices[Node.Indices[i + 1]],
				Node.Vertices[Node.Indices[i + 2]],
			};
			UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendTriangulatedPolygon3D(
				TargetMesh, PrimitiveOptions, FTransform::Identity, Triangle);
			++Triangles;
		}
	}

	if (Triangles > 0)
	{
		UGeometryScriptLibrary_MeshNormalsFunctions::RecomputeNormals(
			TargetMesh, FGeometryScriptCalculateNormalsOptions());
	}
	return Triangles;
}

int32 UOSMCityGeometry::AppendRibbons(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh)
	{
		return 0;
	}
	const FGeometryScriptPrimitiveOptions PrimitiveOptions = DefaultPrimitiveOptions();
	int32 Built = 0;

	for (const FOSMRibbon& Node : Scene.Ribbons)
	{
		const float HalfWidth = FMath::Max(50.f, Node.WidthCm * 0.5f);
		// Layer separates stacked strips; a tunnel drawn at street level would pave over
		// the road above it.
		const float Z = Options.RibbonZOffsetCm + Node.Layer * Options.LayerSpacingCm;

		for (int32 i = 0; i + 1 < Node.Points.Num(); ++i)
		{
			const FVector2D A = Node.Points[i];
			const FVector2D B = Node.Points[i + 1];
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
		for (int32 i = 1; i + 1 < Node.Points.Num(); ++i)
		{
			AppendQuad(TargetMesh, PrimitiveOptions,
				FVector2D(HalfWidth, HalfWidth),
				FTransform(FRotator::ZeroRotator,
					FVector(Node.Points[i].X, Node.Points[i].Y, Z)));
		}
		++Built;
	}

	return Built;
}

bool UOSMCityGeometry::AppendGround(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
	const FOSMBuildOptions& Options)
{
	if (!TargetMesh || !Scene.BoundsCm.bIsValid)
	{
		return false;
	}
	const FVector2D Padding(Options.GroundPaddingCm * 2.f, Options.GroundPaddingCm * 2.f);
	const FVector2D Size = Scene.BoundsCm.GetSize() + Padding;
	const FVector2D Centre = Scene.BoundsCm.GetCenter();

	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendBox(
		TargetMesh, DefaultPrimitiveOptions(),
		FTransform(FRotator::ZeroRotator, FVector(Centre.X, Centre.Y, -100.f)),
		Size.X, Size.Y, /*DimensionZ=*/100.f);
	return true;
}
