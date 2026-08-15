#include "OSMCityBuilder.h"

#include "Components/DynamicMeshComponent.h"
#include "OSMCityGeometry.h"
#include "UDynamicMesh.h"

DEFINE_LOG_CATEGORY_STATIC(LogOSMBuilder, Log, All);

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

	FOSMScene Scene;
	FString Error;
	if (!UOSMCityDataLibrary::LoadSceneFromDirectory(CityDataDir, Scene, Error))
	{
		LastBuildSummary = FString::Printf(TEXT("load failed: %s"), *Error);
		UE_LOG(LogOSMBuilder, Warning, TEXT("%s"), *LastBuildSummary);
		return;
	}

	if (bGenerateGround && GroundMesh)
	{
		UOSMCityGeometry::AppendGround(GroundMesh->GetDynamicMesh(), Scene, BuildOptions);
		GroundMesh->NotifyMeshUpdated();
	}
	if (bGenerateRoads && RoadsMesh)
	{
		LastRoadCount = UOSMCityGeometry::AppendRibbons(RoadsMesh->GetDynamicMesh(), Scene, BuildOptions);
		RoadsMesh->NotifyMeshUpdated();
	}
	if (bGenerateBuildings && BuildingsMesh)
	{
		LastBuildingCount = UOSMCityGeometry::AppendExtrudes(BuildingsMesh->GetDynamicMesh(), Scene, BuildOptions);
		UOSMCityGeometry::AppendMeshes(BuildingsMesh->GetDynamicMesh(), Scene, BuildOptions);
		BuildingsMesh->NotifyMeshUpdated();
	}

	const FVector2D Extent = Scene.BoundsCm.GetSize();
	LastBuildSummary = FString::Printf(
		TEXT("area '%s' | %d buildings | %d roads | extent %.0f x %.0f m | origin %.5f,%.5f"),
		*Scene.AreaName, LastBuildingCount, LastRoadCount,
		Extent.X / 100.0, Extent.Y / 100.0, Scene.OriginLat, Scene.OriginLon);
	UE_LOG(LogOSMBuilder, Log, TEXT("%s"), *LastBuildSummary);
}
