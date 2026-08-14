// Data model for the artefacts produced by pipeline/osm2pcg.
// All coordinates are already in UE centimetres, in the pipeline's convention:
//   +X = North, +Y = East, +Z = Up, origin = the area's bbox centre.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "OSMCityData.generated.h"

/** One OSM building footprint plus its derived height. */
USTRUCT(BlueprintType)
struct FOSMBuilding
{
	GENERATED_BODY()

	/** OSM way/relation id, kept so generated geometry can be traced back to source. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int64 OsmId = 0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString Kind;

	/** Extrusion height in cm (from height / building:levels tags, else estimated). */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float HeightCm = 0.f;

	/** Ground offset in cm for building:part / min_height. Usually 0. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float BaseCm = 0.f;

	/** "tag:height" | "tag:levels" | "estimate:type=..." | "estimate:default". */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString HeightSource;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FVector2D CentroidCm = FVector2D::ZeroVector;

	/** Footprint exterior ring, CCW, not closed (first point is not repeated). */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> OutlineCm;

	/** Minimum-area oriented bounding box, for the simple box-per-building path. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FVector2D BoxCenterCm = FVector2D::ZeroVector;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float BoxLengthCm = 0.f;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float BoxWidthCm = 0.f;

	/** Yaw of the box long axis, degrees about +Z, measured from +X toward +Y. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float BoxYawDeg = 0.f;
};

/** One OSM highway centreline. */
USTRUCT(BlueprintType)
struct FOSMRoad
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int64 OsmId = 0;

	/** OSM highway=* value, e.g. "primary", "residential". */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString RoadClass;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString RoadName;

	/** Full carriageway width in cm (from width tag, else per-class default). */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float WidthCm = 0.f;

	/** OSM layer tag; >0 for bridges, <0 for tunnels. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int32 Layer = 0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> PointsCm;
};

/** Water / park / landuse polygon. */
USTRUCT(BlueprintType)
struct FOSMAreaPoly
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int64 OsmId = 0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString Kind;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> OutlineCm;
};

/** Whole translated area: the parsed contents of data/out/<area>/city.json. */
USTRUCT(BlueprintType)
struct FOSMCity
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString AreaName;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	double OriginLat = 0.0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	double OriginLon = 0.0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMBuilding> Buildings;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMRoad> Roads;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMAreaPoly> Water;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMAreaPoly> Green;

	/** XY extent of all imported geometry, cm. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FBox2D BoundsCm = FBox2D(ForceInit);

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	bool bValid = false;
};

UCLASS()
class CITYGEN_API UOSMCityDataLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Load a city.json produced by `osm2pcg`.
	 * @param FilePath absolute path, or a path relative to the project Content dir.
	 */
	UFUNCTION(BlueprintCallable, Category = "OSM")
	static bool LoadCityFromJsonFile(const FString& FilePath, FOSMCity& OutCity, FString& OutError);

	/** Same, from an in-memory JSON string. */
	UFUNCTION(BlueprintCallable, Category = "OSM")
	static bool LoadCityFromJsonString(const FString& Json, FOSMCity& OutCity, FString& OutError);

	/** Resolve a possibly-relative data path against the project Content dir. */
	UFUNCTION(BlueprintPure, Category = "OSM")
	static FString ResolveDataPath(const FString& FilePath);
};
