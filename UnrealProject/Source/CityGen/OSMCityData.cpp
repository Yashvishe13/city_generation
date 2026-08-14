#include "OSMCityData.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogOSMCity, Log, All);

namespace
{
	/** [x, y] -> FVector2D. Pipeline already emits UE cm in (X=North, Y=East). */
	bool ParsePoint(const TSharedPtr<FJsonValue>& Value, FVector2D& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Pair = nullptr;
		if (!Value.IsValid() || !Value->TryGetArray(Pair) || Pair->Num() < 2)
		{
			return false;
		}
		Out = FVector2D((*Pair)[0]->AsNumber(), (*Pair)[1]->AsNumber());
		return true;
	}

	void ParsePointArray(const TSharedPtr<FJsonObject>& Obj, const FString& Field, TArray<FVector2D>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!Obj->TryGetArrayField(Field, Arr))
		{
			return;
		}
		Out.Reserve(Arr->Num());
		for (const TSharedPtr<FJsonValue>& Entry : *Arr)
		{
			FVector2D P;
			if (ParsePoint(Entry, P))
			{
				Out.Add(P);
			}
		}
	}

	int64 ParseId(const TSharedPtr<FJsonObject>& Obj)
	{
		double Raw = 0.0;
		Obj->TryGetNumberField(TEXT("id"), Raw);
		return static_cast<int64>(Raw);
	}

	void ParseAreaArray(const TSharedPtr<FJsonObject>& Root, const FString& Field, TArray<FOSMAreaPoly>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!Root->TryGetArrayField(Field, Arr))
		{
			return;
		}
		for (const TSharedPtr<FJsonValue>& Entry : *Arr)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!Entry->TryGetObject(Obj))
			{
				continue;
			}
			FOSMAreaPoly Area;
			Area.OsmId = ParseId(*Obj);
			(*Obj)->TryGetStringField(TEXT("kind"), Area.Kind);
			ParsePointArray(*Obj, TEXT("outline"), Area.OutlineCm);
			if (Area.OutlineCm.Num() >= 3)
			{
				Out.Add(MoveTemp(Area));
			}
		}
	}
}

FString UOSMCityDataLibrary::ResolveDataPath(const FString& FilePath)
{
	if (FPaths::IsRelative(FilePath))
	{
		return FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir() / FilePath);
	}
	return FilePath;
}

bool UOSMCityDataLibrary::LoadCityFromJsonFile(const FString& FilePath, FOSMCity& OutCity, FString& OutError)
{
	const FString Resolved = ResolveDataPath(FilePath);
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Resolved))
	{
		OutError = FString::Printf(TEXT("could not read '%s'"), *Resolved);
		UE_LOG(LogOSMCity, Error, TEXT("%s"), *OutError);
		return false;
	}
	return LoadCityFromJsonString(Json, OutCity, OutError);
}

bool UOSMCityDataLibrary::LoadCityFromJsonString(const FString& Json, FOSMCity& OutCity, FString& OutError)
{
	OutCity = FOSMCity();

	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = TEXT("malformed JSON");
		return false;
	}

	// --- manifest: origin + bounds, so georegistration is inspectable in-editor.
	const TSharedPtr<FJsonObject>* Manifest = nullptr;
	if (Root->TryGetObjectField(TEXT("manifest"), Manifest))
	{
		const TSharedPtr<FJsonObject>* Area = nullptr;
		if ((*Manifest)->TryGetObjectField(TEXT("area"), Area))
		{
			(*Area)->TryGetStringField(TEXT("name"), OutCity.AreaName);
		}
		const TSharedPtr<FJsonObject>* Proj = nullptr;
		if ((*Manifest)->TryGetObjectField(TEXT("projection"), Proj))
		{
			(*Proj)->TryGetNumberField(TEXT("origin_lat"), OutCity.OriginLat);
			(*Proj)->TryGetNumberField(TEXT("origin_lon"), OutCity.OriginLon);
		}
	}

	// --- buildings
	const TArray<TSharedPtr<FJsonValue>>* Buildings = nullptr;
	if (Root->TryGetArrayField(TEXT("buildings"), Buildings))
	{
		OutCity.Buildings.Reserve(Buildings->Num());
		for (const TSharedPtr<FJsonValue>& Entry : *Buildings)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!Entry->TryGetObject(Obj))
			{
				continue;
			}

			FOSMBuilding B;
			B.OsmId = ParseId(*Obj);
			(*Obj)->TryGetStringField(TEXT("kind"), B.Kind);
			(*Obj)->TryGetStringField(TEXT("height_source"), B.HeightSource);

			double Num = 0.0;
			if ((*Obj)->TryGetNumberField(TEXT("height_cm"), Num)) { B.HeightCm = static_cast<float>(Num); }
			if ((*Obj)->TryGetNumberField(TEXT("base_cm"), Num)) { B.BaseCm = static_cast<float>(Num); }

			const TArray<TSharedPtr<FJsonValue>>* Centroid = nullptr;
			if ((*Obj)->TryGetArrayField(TEXT("centroid"), Centroid) && Centroid->Num() >= 2)
			{
				B.CentroidCm = FVector2D((*Centroid)[0]->AsNumber(), (*Centroid)[1]->AsNumber());
			}

			const TSharedPtr<FJsonObject>* Box = nullptr;
			if ((*Obj)->TryGetObjectField(TEXT("obb"), Box))
			{
				double X = 0.0, Y = 0.0;
				(*Box)->TryGetNumberField(TEXT("x"), X);
				(*Box)->TryGetNumberField(TEXT("y"), Y);
				B.BoxCenterCm = FVector2D(X, Y);
				if ((*Box)->TryGetNumberField(TEXT("length_cm"), Num)) { B.BoxLengthCm = static_cast<float>(Num); }
				if ((*Box)->TryGetNumberField(TEXT("width_cm"), Num)) { B.BoxWidthCm = static_cast<float>(Num); }
				if ((*Box)->TryGetNumberField(TEXT("yaw_deg"), Num)) { B.BoxYawDeg = static_cast<float>(Num); }
			}

			ParsePointArray(*Obj, TEXT("outline"), B.OutlineCm);
			if (B.OutlineCm.Num() >= 3 && B.HeightCm > 0.f)
			{
				OutCity.Buildings.Add(MoveTemp(B));
			}
		}
	}

	// --- roads
	const TArray<TSharedPtr<FJsonValue>>* Roads = nullptr;
	if (Root->TryGetArrayField(TEXT("roads"), Roads))
	{
		OutCity.Roads.Reserve(Roads->Num());
		for (const TSharedPtr<FJsonValue>& Entry : *Roads)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!Entry->TryGetObject(Obj))
			{
				continue;
			}

			FOSMRoad R;
			R.OsmId = ParseId(*Obj);
			(*Obj)->TryGetStringField(TEXT("class"), R.RoadClass);
			(*Obj)->TryGetStringField(TEXT("name"), R.RoadName);

			double Num = 0.0;
			if ((*Obj)->TryGetNumberField(TEXT("width_cm"), Num)) { R.WidthCm = static_cast<float>(Num); }
			int32 Layer = 0;
			if ((*Obj)->TryGetNumberField(TEXT("layer"), Layer)) { R.Layer = Layer; }

			ParsePointArray(*Obj, TEXT("points"), R.PointsCm);
			if (R.PointsCm.Num() >= 2)
			{
				OutCity.Roads.Add(MoveTemp(R));
			}
		}
	}

	ParseAreaArray(Root, TEXT("water"), OutCity.Water);
	ParseAreaArray(Root, TEXT("green"), OutCity.Green);

	// --- bounds from everything we actually kept
	for (const FOSMBuilding& B : OutCity.Buildings)
	{
		for (const FVector2D& P : B.OutlineCm) { OutCity.BoundsCm += P; }
	}
	for (const FOSMRoad& R : OutCity.Roads)
	{
		for (const FVector2D& P : R.PointsCm) { OutCity.BoundsCm += P; }
	}

	OutCity.bValid = OutCity.Buildings.Num() > 0 || OutCity.Roads.Num() > 0;
	if (!OutCity.bValid)
	{
		OutError = TEXT("no buildings or roads in payload");
		return false;
	}

	UE_LOG(LogOSMCity, Log,
		TEXT("loaded area '%s': %d buildings, %d roads, %d water, %d green; origin %.6f,%.6f"),
		*OutCity.AreaName, OutCity.Buildings.Num(), OutCity.Roads.Num(),
		OutCity.Water.Num(), OutCity.Green.Num(), OutCity.OriginLat, OutCity.OriginLon);
	return true;
}
