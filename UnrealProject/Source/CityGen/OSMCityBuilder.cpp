#include "OSMCityBuilder.h"

#include "Algo/Reverse.h"
#include "Components/DynamicMeshComponent.h"
#include "GeometryScript/MeshNormalsFunctions.h"
#include "GeometryScript/MeshPrimitiveFunctions.h"
#include "UDynamicMesh.h"

DEFINE_LOG_CATEGORY_STATIC(LogOSMBuilder, Log, All);

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
}

AOSMCityBuilder::AOSMCityBuilder()
{
	PrimaryActorTick.bCanEverTick = false;

	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);

	GroundMesh = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("GroundMesh"));
	GroundMesh->SetupAttachment(Root);

	RoadsMesh = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("RoadsMesh"));
	RoadsMesh->SetupAttachment(Root);

	BuildingsMesh = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("BuildingsMesh"));
	BuildingsMesh->SetupAttachment(Root);
}

void AOSMCityBuilder::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	if (bBuildOnConstruction)
	{
		RebuildCity();
	}
}

void AOSMCityBuilder::ClearCity()
{
	for (UDynamicMeshComponent* Component : { GroundMesh.Get(), RoadsMesh.Get(), BuildingsMesh.Get() })
	{
		if (Component && Component->GetDynamicMesh())
		{
			Component->GetDynamicMesh()->Reset();
			Component->NotifyMeshUpdated();
		}
	}
	LastBuildingCount = 0;
	LastRoadCount = 0;
	LastBuildSummary = TEXT("cleared");
}

void AOSMCityBuilder::RebuildCity()
{
	ClearCity();

	FOSMCity City;
	FString Error;
	if (!UOSMCityDataLibrary::LoadCityFromJsonFile(CityDataPath, City, Error))
	{
		LastBuildSummary = FString::Printf(TEXT("load failed: %s"), *Error);
		UE_LOG(LogOSMBuilder, Warning, TEXT("%s"), *LastBuildSummary);
		return;
	}

	if (bGenerateGround && GroundMesh)
	{
		AppendGround(GroundMesh->GetDynamicMesh(), City, GroundPaddingCm);
		GroundMesh->NotifyMeshUpdated();
	}
	if (bGenerateRoads && RoadsMesh)
	{
		AppendRoads(RoadsMesh->GetDynamicMesh(), City, RoadZOffsetCm);
		RoadsMesh->NotifyMeshUpdated();
		LastRoadCount = City.Roads.Num();
	}
	if (bGenerateBuildings && BuildingsMesh)
	{
		AppendBuildings(BuildingsMesh->GetDynamicMesh(), City, MinFootprintAreaCm2, HeightBiasCm);
		BuildingsMesh->NotifyMeshUpdated();
		LastBuildingCount = City.Buildings.Num();
	}

	const FVector2D Extent = City.BoundsCm.GetSize();
	LastBuildSummary = FString::Printf(
		TEXT("area '%s' | %d buildings | %d roads | extent %.0f x %.0f m | origin %.5f,%.5f"),
		*City.AreaName, LastBuildingCount, LastRoadCount,
		Extent.X / 100.0, Extent.Y / 100.0, City.OriginLat, City.OriginLon);
	UE_LOG(LogOSMBuilder, Log, TEXT("%s"), *LastBuildSummary);
}

void AOSMCityBuilder::AppendBuildings(UDynamicMesh* TargetMesh, const FOSMCity& City,
	float MinAreaCm2, float InHeightBiasCm)
{
	if (!TargetMesh)
	{
		return;
	}
	const FGeometryScriptPrimitiveOptions Options = DefaultPrimitiveOptions();

	for (const FOSMBuilding& B : City.Buildings)
	{
		if (B.OutlineCm.Num() < 3)
		{
			continue;
		}
		if (MinAreaCm2 > 0.f && B.BoxLengthCm * B.BoxWidthCm < MinAreaCm2)
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
			TargetMesh, Options, Placement, Local,
			FMath::Max(50.f, B.HeightCm + InHeightBiasCm),
			/*HeightSteps=*/0, /*bCapped=*/true,
			EGeometryScriptPrimitiveOriginMode::Base);
	}

	UGeometryScriptLibrary_MeshNormalsFunctions::RecomputeNormals(
		TargetMesh, FGeometryScriptCalculateNormalsOptions());
}

void AOSMCityBuilder::AppendRoads(UDynamicMesh* TargetMesh, const FOSMCity& City, float ZOffsetCm)
{
	if (!TargetMesh)
	{
		return;
	}
	const FGeometryScriptPrimitiveOptions Options = DefaultPrimitiveOptions();

	// One flat quad per centreline segment, plus a square patch at each interior
	// vertex so corners do not show a wedge-shaped gap.
	for (const FOSMRoad& R : City.Roads)
	{
		const float HalfWidth = FMath::Max(100.f, R.WidthCm * 0.5f);
		const float Z = ZOffsetCm + R.Layer * 400.f;

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

			// Local quad spans X along the segment, Y across it.
			const TArray<FVector2D> Quad = {
				FVector2D(-Length * 0.5f, -HalfWidth),
				FVector2D(Length * 0.5f, -HalfWidth),
				FVector2D(Length * 0.5f, HalfWidth),
				FVector2D(-Length * 0.5f, HalfWidth),
			};
			const FVector2D Mid = (A + B) * 0.5f;
			const float YawDeg = FMath::RadiansToDegrees(FMath::Atan2(Delta.Y, Delta.X));
			const FTransform Placement(
				FRotator(0.f, YawDeg, 0.f), FVector(Mid.X, Mid.Y, Z));

			UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendTriangulatedPolygon(
				TargetMesh, Options, Placement, Quad, /*bAllowSelfIntersections=*/false);
		}

		for (int32 i = 1; i + 1 < R.PointsCm.Num(); ++i)
		{
			const TArray<FVector2D> Patch = {
				FVector2D(-HalfWidth, -HalfWidth),
				FVector2D(HalfWidth, -HalfWidth),
				FVector2D(HalfWidth, HalfWidth),
				FVector2D(-HalfWidth, HalfWidth),
			};
			const FTransform Placement(
				FRotator::ZeroRotator,
				FVector(R.PointsCm[i].X, R.PointsCm[i].Y, Z));
			UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendTriangulatedPolygon(
				TargetMesh, Options, Placement, Patch, /*bAllowSelfIntersections=*/false);
		}
	}
}

void AOSMCityBuilder::AppendGround(UDynamicMesh* TargetMesh, const FOSMCity& City, float PaddingCm)
{
	if (!TargetMesh || !City.BoundsCm.bIsValid)
	{
		return;
	}
	const FVector2D Size = City.BoundsCm.GetSize() + FVector2D(PaddingCm * 2.f, PaddingCm * 2.f);
	const FVector2D Centre = City.BoundsCm.GetCenter();

	UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendBox(
		TargetMesh, DefaultPrimitiveOptions(),
		FTransform(FRotator::ZeroRotator, FVector(Centre.X, Centre.Y, -100.f)),
		Size.X, Size.Y, /*DimensionZ=*/100.f);
}
