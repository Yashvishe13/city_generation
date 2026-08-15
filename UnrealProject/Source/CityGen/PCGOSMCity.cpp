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
	// One mesh pin, not one per feature class. Each emitted mesh carries the scene node's
	// own tags, so a class the pipeline invents later needs no new pin and no C++.
	Properties.Emplace(PCGOSMCityPins::Meshes, EPCGDataType::DynamicMesh,
		/*bInAllowMultipleConnections=*/true, /*bAllowMultipleData=*/true,
		LOCTEXT("MeshesTooltip",
			"Geometry built from the scene: extruded volumes, appended triangle meshes, "
			"road ribbons and the ground slab. Each data is tagged with its node's tags."));
	Properties.Emplace(PCGOSMCityPins::Splines, EPCGDataType::Spline,
		true, true,
		LOCTEXT("SplinesTooltip", "One spline per ribbon centreline."));
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

	FOSMScene Scene;
	FString Error;
	if (!UOSMCityDataLibrary::LoadSceneFromDirectory(Settings->CityDataDir, Scene, Error))
	{
		PCGLog::LogErrorOnGraph(
			FText::Format(LOCTEXT("LoadFailed", "OSM City Source: {0}"), FText::FromString(Error)),
			Context);
		return true;
	}

	// Downstream Spawn Dynamic Mesh turns each of these into a PCG-managed component, so
	// regenerating replaces rather than stacks.
	auto EmitMesh = [Context](const TArray<FString>& Tags) -> UPCGDynamicMeshData*
	{
		UPCGDynamicMeshData* Data = FPCGContext::NewObject_AnyThread<UPCGDynamicMeshData>(Context);
		FPCGTaggedData& Tagged = Context->OutputData.TaggedData.Emplace_GetRef();
		Tagged.Data = Data;
		Tagged.Pin = PCGOSMCityPins::Meshes;
		for (const FString& Tag : Tags)
		{
			Tagged.Tags.Add(Tag);
		}
		return Data;
	};

	int32 Extruded = 0;
	int32 Triangles = 0;
	int32 Ribbons = 0;

	if (Settings->bOutputExtrudes)
	{
		UPCGDynamicMeshData* Data = EmitMesh({TEXT("extrude")});
		Extruded = UOSMCityGeometry::AppendExtrudes(
			Data->GetMutableDynamicMesh(), Scene, Settings->BuildOptions);
	}

	if (Settings->bOutputMeshes && Scene.Meshes.Num() > 0)
	{
		UPCGDynamicMeshData* Data = EmitMesh({TEXT("mesh")});
		Triangles = UOSMCityGeometry::AppendMeshes(
			Data->GetMutableDynamicMesh(), Scene, Settings->BuildOptions);
	}

	if (Settings->bOutputRibbons)
	{
		UPCGDynamicMeshData* Data = EmitMesh({TEXT("ribbon")});
		Ribbons = UOSMCityGeometry::AppendRibbons(
			Data->GetMutableDynamicMesh(), Scene, Settings->BuildOptions);
	}

	if (Settings->bOutputGround)
	{
		UPCGDynamicMeshData* Data = EmitMesh({TEXT("ground")});
		UOSMCityGeometry::AppendGround(
			Data->GetMutableDynamicMesh(), Scene, Settings->BuildOptions);
	}

	if (Settings->bOutputSplines)
	{
		for (const FOSMRibbon& Ribbon : Scene.Ribbons)
		{
			const float Z = Settings->BuildOptions.RibbonZOffsetCm
				+ Ribbon.Layer * Settings->BuildOptions.LayerSpacingCm;

			TArray<FSplinePoint> SplinePoints;
			SplinePoints.Reserve(Ribbon.Points.Num());
			for (int32 i = 0; i < Ribbon.Points.Num(); ++i)
			{
				// Linear points: the centrelines are already polylines, and curving them
				// would move the geometry off the surveyed shape.
				SplinePoints.Emplace(static_cast<float>(i),
					FVector(Ribbon.Points[i].X, Ribbon.Points[i].Y, Z),
					ESplinePointType::Linear);
			}

			UPCGSplineData* SplineData = FPCGContext::NewObject_AnyThread<UPCGSplineData>(Context);
			SplineData->Initialize(SplinePoints, /*bInClosedLoop=*/false, FTransform::Identity);

			FPCGTaggedData& Tagged = Context->OutputData.TaggedData.Emplace_GetRef();
			Tagged.Data = SplineData;
			Tagged.Pin = PCGOSMCityPins::Splines;
			for (const FString& Tag : Ribbon.Tags)
			{
				Tagged.Tags.Add(Tag);
			}
		}
	}

	UE_LOG(LogPCGOSMCity, Log,
		TEXT("OSM City Source: area '%s' -> %d extruded, %d triangles, %d ribbons, %d splines"),
		*Scene.AreaName, Extruded, Triangles, Ribbons,
		Settings->bOutputSplines ? Scene.Ribbons.Num() : 0);

	return true;
}

#undef LOCTEXT_NAMESPACE
