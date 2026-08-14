// PCG source node: reads the translated OSM export and emits it as PCG data.
//
//   Buildings   (Dynamic Mesh)  extruded footprints
//   Roads       (Dynamic Mesh)  centreline ribbons
//   Ground      (Dynamic Mesh)  ground slab
//   RoadSplines (Spline)        one spline per centreline, for spline-mesh roads
//
// Wire the mesh pins into Spawn Dynamic Mesh nodes; PCG owns the resulting
// components, so regenerating never leaves stale geometry behind.
#pragma once

#include "PCGSettings.h"

#include "OSMCityGeometry.h"

#include "PCGOSMCity.generated.h"

namespace PCGOSMCityPins
{
	const FName Buildings = TEXT("Buildings");
	const FName Roads = TEXT("Roads");
	const FName Ground = TEXT("Ground");
	const FName RoadSplines = TEXT("RoadSplines");
}

UCLASS(BlueprintType, ClassGroup = (Procedural))
class CITYGEN_API UPCGOSMCitySettings : public UPCGSettings
{
	GENERATED_BODY()

public:
	//~Begin UPCGSettings interface
#if WITH_EDITOR
	virtual FName GetDefaultNodeName() const override { return FName(TEXT("OSMCity")); }
	virtual FText GetDefaultNodeTitle() const override
	{
		return NSLOCTEXT("PCGOSMCity", "NodeTitle", "OSM City Source");
	}
	virtual FText GetNodeTooltipText() const override
	{
		return NSLOCTEXT("PCGOSMCity", "NodeTooltip",
			"Loads a city.json produced by the osm2pcg pipeline and outputs building, "
			"road and ground geometry plus road splines.");
	}
	virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::Spatial; }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override { return {}; }
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
	//~End UPCGSettings interface

public:
	/** city.json path; relative paths resolve against the project Content dir. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	FString CityDataPath = TEXT("Data/city.json");

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	FOSMBuildOptions BuildOptions;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputBuildings = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputRoads = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputGround = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputRoadSplines = true;
};

class FPCGOSMCityElement : public IPCGElement
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;

	/** The data lives in a file on disk, so cached results can silently go stale. */
	virtual bool IsCacheable(const UPCGSettings*) const override { return false; }
	virtual bool CanExecuteOnlyOnMainThread(FPCGContext*) const override { return false; }
};
