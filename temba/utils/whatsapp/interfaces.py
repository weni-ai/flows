from abc import ABC, abstractmethod


class FacebookCatalog(ABC):
    @abstractmethod
    def get_facebook_catalogs(waba_id):
        pass
