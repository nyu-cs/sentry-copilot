from sentry_copilot.routes.repository import MapRepository

if __name__ == "__main__":
    repository = MapRepository.from_directory("data/maps")
    for map_id in repository.list_ids():
        print(map_id)
