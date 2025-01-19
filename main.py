from Source.Core.Exceptions import ParsingError, TitleNotFound
from Source.Core.ImagesDownloader import ImagesDownloader
from Source.Core.Base.BaseExtension import BaseExtension
from Source.Core.Formats import BaseTitle, By
from Source.Core.Collector import Collector
from Source.Core.Timer import Timer
from Source.CLI import Templates

from ...main import SITE

from dublib.WebRequestor import Protocols, WebConfig, WebLibs, WebRequestor
from dublib.CLI.Terminalyzer import Command, ParsedCommandData
from dublib.Methods.Filesystem import NormalizePath, WriteJSON
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

	def __Save(self, cards: dict, dir: str):
		"""
		Сохраняет описание карточек.
			cards – описание;\n
			dir – используемое имя директории карточек.
		"""

		Directory = f"{self.__OutputDirectory}/{dir}"
		ImagesDirectory = f"{Directory}/images"
		if not os.path.exists(Directory): os.makedirs(Directory)
		if not os.path.exists(ImagesDirectory): os.makedirs(ImagesDirectory)
		Index = 0
		Count = len(cards["cards"])

		if os.listdir(ImagesDirectory) and self.force_mode:
			shutil.rmtree(ImagesDirectory)
			os.makedirs(ImagesDirectory)

		for Card in cards["cards"]:
			Index += 1
			Filename = Card["image"]["filename"]
			ItalicFilename = TextStyler(Filename).decorate.italic
			print(f"[{Index} / {Count}] Downloading \"{ItalicFilename}\"... ", end = "")
			Result = self.__Downloader.image(Card["image"]["link"], ImagesDirectory)
			print(Result.message, flush = True)
			if Result.message != "Already exists.": sleep(self.parser_settings.common.delay)

		WriteJSON(f"{Directory}/cards.json", cards)
		Slug = TextStyler(cards["title_slug"]).decorate.bold
		self.portals.info(f"Cards in {Slug} parsed: {Count}.")

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
		self.__OutputDirectory = self.temp if not self.settings["output_directory"] else NormalizePath(self.settings["output_directory"])

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
				if TitlesCount > 1: Templates.parsing_progress(Index, TitlesCount)
				try: self.parse(Titles[Index])
				except TitleNotFound: NotFoundCount += 1
				except ParsingError: ErrorsCount += 1
				else: ParsedCount += 1

			Templates.parsing_summary(ParsedCount, NotFoundCount, ErrorsCount)

	#==========================================================================================#
	# >>>>> ПУБЛИЧНЫЕ МЕТОДЫ <<<<< #
	#==========================================================================================#

	def parse(self, slug: str):
		"""
		Парсит все карточки тайтла.
			title – алиас тайтла.
		"""

		TimerObject = Timer(start = True)
		title_id = self.__SlugToID(slug)
		UsedName = str(title_id) if self.parser_settings.common.use_id_as_filename else slug

		Slug = TextStyler(slug).decorate.bold

		if os.path.exists(f"{self.__OutputDirectory}/{UsedName}") and not self.force_mode:
			self.portals.info(f"Parsing cards from {Slug} (ID: {title_id})... Already parsed. Skipped.")
			self.portals.info("Done in " + TimerObject.ends() + ".")
			return

		self.portals.info(f"Parsing cards from {Slug} (ID: {title_id})...")

		Cards = {
			"title_id": title_id,
			"title_slug": slug,
			"cards": []
		}
		
		CardsInfo = self.__GetCardsInfo(title_id)

		if CardsInfo:
			Cards["cards"] = [self.__ParseCardInfo(Card) for Card in CardsInfo]
			self.__Save(Cards, UsedName)

		else: self.portals.info(f"Title doesn't have any cards.")

		self.portals.info("Done in " + TimerObject.ends() + ".")