// PCG source node: reads the translated OSM export and emits it as PCG data.
//
//   Meshes  (Dynamic Mesh)  everything built from the scene, each data tagged with the
//                           node tags it came from
//   Splines (Spline)        one spline per ribbon centreline
//
// Wire Meshes into a Spawn Dynamic Mesh node; PCG owns the resulting components, so
// regenerating never leaves stale geometry behind. A feature class the pipeline invents
// later arrives on the same pin with different tags - no new pin, no C++.
#pragma once

#include "PCGSettings.h"

#include "OSMCityGeometry.h"

#include "PCGOSMCity.generated.h"

namespace PCGOSMCityPins
{
	// One mesh pin for every kind of geometry; the data carries tags instead.
	const FName Meshes = TEXT("Meshes");
	const FName Splines = TEXT("Splines");
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
			"Loads the scene.json produced by the generated pipeline for an area and "
			"outputs its geometry as dynamic meshes plus centreline splines.");
	}
	virtual EPCGSettingsType GetType() const override { return EPCGSettingsType::Spatial; }
#endif

protected:
	virtual TArray<FPCGPinProperties> InputPinProperties() const override { return {}; }
	virtual TArray<FPCGPinProperties> OutputPinProperties() const override;
	virtual FPCGElementPtr CreateElement() const override;
	//~End UPCGSettings interface

public:
	/** Directory of converter output; relative paths resolve against Content. */
	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	FString CityDataDir = TEXT("Data/City");

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	FOSMBuildOptions BuildOptions;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputExtrudes = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputMeshes = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputRibbons = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputGround = true;

	UPROPERTY(BlueprintReadWrite, EditAnywhere, Category = Settings, meta = (PCG_Overridable))
	bool bOutputSplines = true;
};

class FPCGOSMCityElement : public IPCGElement
{
protected:
	virtual bool ExecuteInternal(FPCGContext* Context) const override;

	/** The data lives in a file on disk, so cached results can silently go stale. */
	virtual bool IsCacheable(const UPCGSettings*) const override { return false; }
	virtual bool CanExecuteOnlyOnMainThread(FPCGContext*) const override { return false; }
};
