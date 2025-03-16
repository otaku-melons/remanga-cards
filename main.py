from Source.Core.Exceptions import ParsingError, TitleNotFound
from Source.Core.ImagesDownloader import ImagesDownloader
from Source.Core.Base.BaseExtension import BaseExtension
from Source.Core.Formats import BaseTitle, By
from Source.Core.Collector import Collector
from Source.Core.Formats.Manga import Manga
from Source.Core.Timer import Timer
from Source.CLI import Templates

from ...main import SITE

from dublib.Methods.Filesystem import ListDir, ReadTextFile, WriteTextFile
from dublib.WebRequestor import Protocols, WebConfig, WebLibs, WebRequestor
from dublib.CLI.Terminalyzer import Command, ParsedCommandData
from dublib.CLI.TextStyler import TextStyler
from dublib.Methods.Data import Zerotify
from dublib.Polyglot import HTML

from time import sleep

import shutil
import os

#==========================================================================================#
# >>>>> РАСШИРЕНИЕ <<<<< #
#==========================================================================================#

class Extension(BaseExtension):

	#==========================================================================================#
	# >>>>> ПРИВАТНЫЕ МЕТОДЫ <<<<< #
	#==========================================================================================#

	def __DownloadImages(self, cards: list[dict], used_filename: str):
		"""
		Скачивает изображения карт.
			cards – данные карт;\n
			used_filename – используемое имя описательного файла.
		"""

		ImagesDirectory = f"{self._ParserSettings.directories.images}/{used_filename}/cards"
		if not os.path.exists(ImagesDirectory): os.makedirs(ImagesDirectory)
		Index = 0
		Count = len(cards)

		if ListDir(ImagesDirectory) and self.force_mode:
			shutil.rmtree(ImagesDirectory)
			os.makedirs(ImagesDirectory)

		for Card in cards:
			Index += 1
			Filename = Card["image"]["filename"]
			ItalicFilename = TextStyler(Filename).decorate.italic
			print(f"[{Index} / {Count}] Downloading \"{ItalicFilename}\"... ", end = "")

			if os.path.exists(f"{ImagesDirectory}/{Filename}"):
				print("Already exists.")
				continue

			Result = self.__Downloader.image(Card["image"]["link"], ImagesDirectory)
			Result.print_messages()
			if Result.messages[-1] != "Already exists.": sleep(self.parser_settings.common.delay)

	def __GetCardsInfo(self, title_id: int) -> list[dict]:
		"""
		Возвращает список данных карточек.
			title_id – ID тайтла.
		"""

		IsParsed = False
		Page = 1
		Info = list()

		while not IsParsed:
			Response = self.requestor.get(f"https://{SITE}/api/inventory/{title_id}/cards/?count=30&page={Page}")
		
			if Response.status_code == 200: 
				Info += [Element for Element in Response.json["results"]]
				if Info: self.portals.info(f"Cards on page {Page} parsed.")
				Page += 1
				sleep(self.parser_settings.common.delay)

			elif Response.status_code == 404 and Page > 1:
				IsParsed = True

			elif Response.status_code == 404:
				IsParsed = True

			else:
				self.portals.request_error(Response, "Unable to request cards info.")
				break

		return Info

	def __ParseCardInfo(self, info: dict) -> dict:
		"""
		Преобразует данные карточки в более удобный формат.
			info – данные карточки.
		"""

		Data = {
			"id": info["id"],
			"rank": info["rank"].replace("rank_", "").upper(),
			"description": Zerotify(HTML(info["description"]).plain_text) if info["description"] else None,
			"image": {
				"link": "https://remanga.org/media/" + info["cover"]["high"],
				"filename": info["cover"]["high"].split("/")[-1]
			},
			"author": {
				"id": info["author"]["id"],
				"name": info["author"]["username"]
			},
			"character": {
				"id": None,
				"name": None,
				"another_names": [],
				"description": None
			}
		}

		if info["character"]:
			Data["character"]["id"] = info["character"]["id"]
			Data["character"]["name"] = info["character"]["name"]
			Data["character"]["description"] = Zerotify(HTML(info["character"]["description"]).plain_text) if info["character"]["description"] else None

		return Data

	def __SlugToID(self, slug: str) -> int:
		"""
		Преобразует алиас тайтла в ID.
			slug – алиас.
		"""

		Response = self.requestor.get(f"https://{SITE}/api/titles/{slug}/")

		if Response.status_code == 200:
			return Response.json["content"]["id"]
		
		elif Response.status_code == 404:
			Title = BaseTitle(self.system_objects)
			Title.open(slug, By.Slug, exception = False)
			Title.set_slug(slug)

			Slug = TextStyler(slug).decorate.bold
			NoteID = f" (ID: {Title.id})" if Title.id else ""
			print(f"Parsing cards from {Slug}{NoteID}... ")

			self.portals.title_not_found(Title)

		else:
			AuthorizationWarning = " May be authorization required." if not self._ParserSettings.custom["token"] else ""
			self.portals.request_error(Response, f"Unable convert slug \"{slug}\" to ID.{AuthorizationWarning}")

	#==========================================================================================#
	# >>>>> ПЕРЕОПРЕДЕЛЯЕМЫЕ МЕТОДЫ <<<<< #
	#==========================================================================================#

	def _GenerateCommandsList(self) -> list[Command]:
		"""Возвращает список описаний команд."""

		CommandsList = list()

		Com = Command("parse", "Parse cards info.")
		ComPos = Com.create_position("TARGET", "Title ID or slug.", important = True)
		ComPos.add_argument(description = "Title ID or slug.")
		ComPos.add_flag("collection", "Parse slugs from Collection.txt file.")
		ComPos.add_flag("local", description = "Parse cards from all local titles.")
		ComPos.add_flag("updates", "Parse titles with new carsds since last parsing.")
		Com.add_key("from", description = "Skip titles before this slug.")
		CommandsList.append(Com)

		return CommandsList
	
	def _InitializeRequestor(self) -> WebRequestor:
		"""Инициализирует модуль WEB-запросов."""

		Config = WebConfig()
		Config.select_lib(WebLibs.requests)
		Config.set_retries_count(self._ParserSettings.common.retries)
		if self._ParserSettings.custom["token"]: Config.add_header("Authorization", self._ParserSettings.custom["token"])
		Config.add_header("Referer", f"https://{SITE}/")
		WebRequestorObject = WebRequestor(Config)

		if self._ParserSettings.proxy.enable: WebRequestorObject.add_proxy(
			Protocols.HTTPS,
			host = self._ParserSettings.proxy.host,
			port = self._ParserSettings.proxy.port,
			login = self._ParserSettings.proxy.login,
			password = self._ParserSettings.proxy.password
		)

		return WebRequestorObject

	def _PostInitMethod(self):
		"""Метод, выполняющийся после инициализации объекта."""

		self.__Downloader = ImagesDownloader(self.system_objects, self.requestor)

	def _ProcessCommand(self, command: ParsedCommandData):
		"""
		Вызывается для обработки переданной расширению команды.
			command – данные команды.
		"""

		if command.name == "parse":
			Titles = list()
			StartIndex = 0

			if command.check_flag("local"):
				TimerObject = Timer(start = True)
				print("Scanning titles... ", end = "", flush = True)
				CollectorObject = Collector(self.system_objects)
				Titles = CollectorObject.get_local_identificators(By.Slug)
				ElapsedTime = TimerObject.ends()
				print(f"Done in {ElapsedTime}.")

			elif command.check_flag("collection"):
				TimerObject = Timer(start = True)
				print("Scanning titles... ", end = "", flush = True)
				Titles = Collector(self.system_objects, merge = True).slugs
				ElapsedTime = TimerObject.ends()
				print(f"Done in {ElapsedTime}.")

			elif command.check_flag("updates"):
				TimerObject = Timer(start = True)
				print("Collecting updates... ", flush = True)
				Titles = self.get_updated_titles()
				ElapsedTime = TimerObject.ends()
				Count = len(Titles)
				print(f"{Count} updates collected in {ElapsedTime}.")

			else: Titles.append(command.arguments[0])

			if command.check_key("from"):
				StartSlug = command.get_key_value("from")

				if StartSlug in Titles:
					StartIndex = Titles.index(StartSlug)
					StartSlug = TextStyler(StartSlug).decorate.bold
					self._Portals.info(f"Parsing will be started from \"{StartSlug}\".")

				else: self._Portals.warning("No starting slug in collection. Ignored.")

			if self.force_mode: self.portals.warning("Exists images will be deleted.")

			ParsedCount = 0
			NotFoundCount = 0
			ErrorsCount = 0
			TitlesCount = len(Titles)

			for Index in range(StartIndex, TitlesCount):
				Result = None

				if TitlesCount > 1: Templates.parsing_progress(Index, TitlesCount)

				try: Result = self.parse(Titles[Index])
				except TitleNotFound: NotFoundCount += 1
				except ParsingError: ErrorsCount += 1
				else:
					if Result: ParsedCount += 1

			Templates.parsing_summary(ParsedCount, NotFoundCount, ErrorsCount)

	#==========================================================================================#
	# >>>>> ПУБЛИЧНЫЕ МЕТОДЫ <<<<< #
	#==========================================================================================#

	def get_updated_titles(self) -> tuple[str]:
		"""Возвращает последовательность алиасов тайтлов, для которых вышли новые карты с момента последнего запуска."""

		PreviousCardID = None

		MemoryFile = f"{self._Temper.extension_temp}/last_card_id.txt"
		if os.path.exists(MemoryFile): PreviousCardID = int(ReadTextFile(MemoryFile).strip())

		LastCardID = None
		Titles = list()
		IsParsingDone = False
		Page = 1

		while not IsParsingDone:
			Response = self._Requestor.get(f"https://{SITE}/api/inventory/catalog/?count=30&ordering=-id&page={Page}")

			if Response.status_code == 200: 

				for Card in Response.json["results"]:
					if not LastCardID: LastCardID = Card["id"]
					if not PreviousCardID or Card["id"] > PreviousCardID: Titles.append(Card["title"]["dir"])
					elif Card["id"] <= PreviousCardID: IsParsingDone = True

					if not PreviousCardID:
						self.portals.warning("First parsing. Collection only one slug.")
						IsParsingDone = True
						break

				if Titles: self.portals.info(f"Cards on page {Page} parsed.")
				sleep(self.parser_settings.common.delay)

			else:
				self.portals.request_error(Response, "Unable to request cards info.")
				break

			Page += 1

		WriteTextFile(MemoryFile, str(LastCardID))
		
		return tuple(set(Titles))

	def parse(self, slug: str) -> dict | None:
		"""
		Парсит все карточки тайтла и прикрепляет их к локальным данным.
			title – алиас тайтла.
		"""

		TimerObject = Timer(start = True)
		title_id = self.__SlugToID(slug)
		Title = Manga(self._SystemObjects)
		BoldSlug = TextStyler(slug).decorate.bold

		try: 
			if self._ParserSettings.common.use_id_as_filename: Title.open(title_id, By.ID)
			else: Title.open(slug, By.Slug)

		except FileNotFoundError:
			self.portals.warning(f"JSON for {BoldSlug} not found. Parse it first.")
			return

		self.portals.info(f"Parsing cards from {BoldSlug} (ID: {title_id})...")
		Cards: list[dict] = list()
		CardsInfo = self.__GetCardsInfo(title_id)

		if CardsInfo:
			Cards = [self.__ParseCardInfo(Card) for Card in CardsInfo]
			Title["cards"] = Cards
			self.__DownloadImages(Cards, Title.used_filename)
			Title.save()
			self.portals.info(f"Cards in {BoldSlug} parsed: " + str(len(Cards)) + ".")

		else: self.portals.info(f"Title doesn't have any cards.")

		self.portals.info("Done in " + TimerObject.ends() + ".")
		
		return Cards