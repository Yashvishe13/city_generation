#include "PCGOSMCity.h"

#include "Components/SplineComponent.h"
#include "Data/PCGDynamicMeshData.h"
#include "Data/PCGSplineData.h"
#include "OSMCityData.h"
#include "PCGContext.h"
#include "UDynamicMesh.h"

#define LOCTEXT_NAMESPACE "PCGOSMCityElement"

DEFINE_LOG_CATEGORY_STATIC(LogPCGOSMCity, Log, All);

TArray<FPCGPinProperties> UPCGOSMCitySettings::OutputPinProperties() const
{
	TArray<FPCGPinProperties> Properties;
	Properties.Emplace(PCGOSMCityPins::Buildings, EPCGDataType::DynamicMesh,
		/*bInAllowMultipleConnections=*/true, /*bAllowMultipleData=*/false,
		LOCTEXT("BuildingsTooltip", "Extruded OSM building footprints."));
	Properties.Emplace(PCGOSMCityPins::Roads, EPCGDataType::DynamicMesh,
		true, false, LOCTEXT("RoadsTooltip", "Flat ribbons along the road centrelines."));
	Properties.Emplace(PCGOSMCityPins::Ground, EPCGDataType::DynamicMesh,
		true, false, LOCTEXT("GroundTooltip", "Ground slab covering the area bounds."));
	Properties.Emplace(PCGOSMCityPins::RoadSplines, EPCGDataType::Spline,
		true, true, LOCTEXT("RoadSplinesTooltip", "One spline per road centreline."));
	return Properties;
}

FPCGElementPtr UPCGOSMCitySettings::CreateElement() const
{
	return MakeShared<FPCGOSMCityElement>();
}

bool FPCGOSMCityElement::ExecuteInternal(FPCGContext* Context) const
{
	TRACE_CPUPROFILER_EVENT_SCOPE(FPCGOSMCityElement::Execute);
	check(Context);

	const UPCGOSMCitySettings* Settings = Context->GetInputSettings<UPCGOSMCitySettings>();
	check(Settings);

	FOSMCity City;
	FString Error;
	if (!UOSMCityDataLibrary::LoadCityFromJsonFile(Settings->CityDataPath, City, Error))
	{
		PCGLog::LogErrorOnGraph(
			FText::Format(LOCTEXT("LoadFailed", "OSM City Source: {0}"), FText::FromString(Error)),
			Context);
		return true;
	}

	// Each mesh pin emits a single dynamic mesh; downstream Spawn Dynamic Mesh turns
	// it into a PCG-managed component, so a regenerate replaces rather than stacks.
	auto EmitMesh = [Context](const FName Pin) -> UPCGDynamicMeshData*
	{
		UPCGDynamicMeshData* Data = FPCGContext::NewObject_AnyThread<UPCGDynamicMeshData>(Context);
		FPCGTaggedData& Tagged = Context->OutputData.TaggedData.Emplace_GetRef();
		Tagged.Data = Data;
		Tagged.Pin = Pin;
		return Data;
	};

	int32 BuildingCount = 0;
	int32 RoadCount = 0;

	if (Settings->bOutputBuildings)
	{
		UPCGDynamicMeshData* Data = EmitMesh(PCGOSMCityPins::Buildings);
		BuildingCount = UOSMCityGeometry::AppendBuildings(
			Data->GetMutableDynamicMesh(), City, Settings->BuildOptions);
	}

	if (Settings->bOutputRoads)
	{
		UPCGDynamicMeshData* Data = EmitMesh(PCGOSMCityPins::Roads);
		RoadCount = UOSMCityGeometry::AppendRoads(
			Data->GetMutableDynamicMesh(), City, Settings->BuildOptions);
	}

	if (Settings->bOutputGround)
	{
		UPCGDynamicMeshData* Data = EmitMesh(PCGOSMCityPins::Ground);
		UOSMCityGeometry::AppendGround(
			Data->GetMutableDynamicMesh(), City, Settings->BuildOptions);
	}

	if (Settings->bOutputRoadSplines)
	{
		const float Z = Settings->BuildOptions.RoadZOffsetCm;
		for (const FOSMRoad& Road : City.Roads)
		{
			TArray<FSplinePoint> SplinePoints;
			SplinePoints.Reserve(Road.PointsCm.Num());
			for (int32 i = 0; i < Road.PointsCm.Num(); ++i)
			{
				// Linear points: OSM centrelines are already polylines, curving them
				// would move the road off the surveyed geometry.
				SplinePoints.Emplace(static_cast<float>(i),
					FVector(Road.PointsCm[i].X, Road.PointsCm[i].Y, Z + Road.Layer * 400.f),
					ESplinePointType::Linear);
			}

			UPCGSplineData* SplineData = FPCGContext::NewObject_AnyThread<UPCGSplineData>(Context);
			SplineData->Initialize(SplinePoints, /*bInClosedLoop=*/false, FTransform::Identity);

			FPCGTaggedData& Tagged = Context->OutputData.TaggedData.Emplace_GetRef();
			Tagged.Data = SplineData;
			Tagged.Pin = PCGOSMCityPins::RoadSplines;
			// Tags let downstream nodes filter by road class, e.g. wider primaries.
			Tagged.Tags.Add(Road.RoadClass);
		}
	}

	UE_LOG(LogPCGOSMCity, Log,
		TEXT("OSM City Source: area '%s' -> %d buildings, %d road ribbons, %d splines"),
		*City.AreaName, BuildingCount, RoadCount,
		Settings->bOutputRoadSplines ? City.Roads.Num() : 0);

	return true;
}

#undef LOCTEXT_NAMESPACE
