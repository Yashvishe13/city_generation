// Data model for the scene contract produced by a generated pipeline
// (agent_scripts/<area>/pipeline.py -> data/ue/<area>/scene.json).
//
// The engine knows three geometric primitives and nothing about OpenStreetMap: no tag
// names, no highway classes, no roof vocabulary. Semantics travel as opaque tags.
// All coordinates are UE centimetres: +X = North, +Y = East, +Z = Up, origin = the
// area's bbox centre.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "OSMCityData.generated.h"

/** One closed ring. A struct because UPROPERTY cannot hold a nested TArray<TArray<>>. */
USTRUCT(BlueprintType)
struct FOSMRing
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> Points;
};

/** kind: "extrude" - a closed ring swept from BaseCm to HeightCm. */
USTRUCT(BlueprintType)
struct FOSMExtrude
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString Id;

	/** Exterior ring, CCW, first vertex not repeated. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> Outline;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMRing> Holes;

	/** Absolute bottom and absolute top, cm. The sweep is the difference. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float BaseCm = 0.f;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float HeightCm = 0.f;

	/** Opaque labels from the pipeline, e.g. "building", "building:part". */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FString> Tags;

	/** Footprint area, cm^2, computed on load. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float AreaCm2 = 0.f;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FVector2D CentroidCm = FVector2D::ZeroVector;
};

/** kind: "mesh" - indexed triangles in absolute world centimetres. */
USTRUCT(BlueprintType)
struct FOSMMesh
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString Id;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector> Vertices;

	/** Three consecutive entries per triangle, indexing into Vertices. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<int32> Indices;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FString> Tags;
};

/** kind: "ribbon" - a polyline widened into a flat strip. */
USTRUCT(BlueprintType)
struct FOSMRibbon
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString Id;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FVector2D> Points;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	float WidthCm = 0.f;

	/** Vertical ordering hint; negative sits below grade. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int32 Layer = 0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FString> Tags;
};

/** A translated area: the contents of data/ue/<area>/scene.json. */
USTRUCT(BlueprintType)
struct FOSMScene
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FString AreaName;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	double OriginLat = 0.0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	double OriginLon = 0.0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMExtrude> Extrudes;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMMesh> Meshes;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	TArray<FOSMRibbon> Ribbons;

	/** XY extent of everything loaded, cm. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	FBox2D BoundsCm = FBox2D(ForceInit);

	/** Nodes whose kind this engine does not build, counted rather than hidden. */
	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	int32 SkippedNodes = 0;

	UPROPERTY(BlueprintReadOnly, Category = "OSM")
	bool bValid = false;
};

UCLASS()
class CITYGEN_API UOSMCityDataLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Load data/ue/<area>/scene.json.
	 * @param DirPath absolute, or relative to the project Content dir.
	 */
	UFUNCTION(BlueprintCallable, Category = "OSM")
	static bool LoadSceneFromDirectory(const FString& DirPath, FOSMScene& OutScene, FString& OutError);

	/** Resolve a possibly-relative data path against the project Content dir. */
	UFUNCTION(BlueprintPure, Category = "OSM")
	static FString ResolveDataPath(const FString& FilePath);
};
